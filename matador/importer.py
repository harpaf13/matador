# coding: utf-8
""" This file implements the base class Spatula
that calls the scrapers and interfaces with the
MongoDB client.
"""

# matador modules
from matador.scrapers.castep_scrapers import castep2dict, param2dict, cell2dict
from matador.scrapers.castep_scrapers import res2dict, dir2dict
from matador.scrapers.experiment_scrapers import expt2dict, synth2dict
from matador.utils.cell_utils import calc_mp_spacing
from matador.version import __version__
# external libraries
import pymongo as pm
# standard library
from random import randint
from collections import defaultdict
from datetime import datetime
from os import walk, getcwd, uname, chmod, rename
from time import sleep
from os.path import realpath, abspath, dirname, getmtime, isfile
from traceback import print_exc
from copy import deepcopy


class Spatula:
    """ The Spatula class implements methods to scrape folders
    and individual files for crystal structures and create a
    MongoDB document for each.

    Files types that can be read are:

        | * CASTEP output
        | * CASTEP .param, .cell input
        | * SHELX (from airss.pl / pyAIRSS) .res output

    """
    def __init__(self, *args):
        """ Set up arguments and initialise DB client. """
        self.args = args[0]
        self.dryrun = self.args['dryrun']
        self.scan = self.args['scan']
        if self.scan:
            self.dryrun = True
        self.debug = self.args['debug']
        self.verbosity = self.args['verbosity'] if self.args['verbosity'] is not None else 0
        self.tags = self.args['tags']
        self.tag_dict = dict()
        self.tag_dict['tags'] = self.tags
        self.import_count = 0
        self.struct_list = []
        # I/O files
        if not self.dryrun:
            logfile_name = 'spatula.err'
            manifest_name = 'spatula.manifest'
            if isfile(logfile_name):
                mtime = getmtime(logfile_name)
                mdate = datetime.fromtimestamp(mtime)
                mdate = str(mdate).split()[0]
                rename(logfile_name, logfile_name + '.' + str(mdate).split()[0])
            if isfile(manifest_name):
                mtime = getmtime(manifest_name)
                mdate = datetime.fromtimestamp(mtime)
                mdate = str(mdate).split()[0]
                rename(manifest_name, manifest_name + '.' + str(mdate).split()[0])

            wordfile = open(dirname(realpath(__file__)) + '/scrapers/words', 'r')
            nounfile = open(dirname(realpath(__file__)) + '/scrapers/nouns', 'r')
            self.wlines = wordfile.readlines()
            self.num_words = len(self.wlines)
            self.nlines = nounfile.readlines()
            self.num_nouns = len(self.nlines)
            wordfile.close()
            nounfile.close()

        elif not self.scan:
            logfile_name = 'spatula.err.dryrun'
            manifest_name = 'spatula.manifest.dryrun'
        if not self.scan:
            self.logfile = open(logfile_name, 'w')
            self.manifest = open(manifest_name, 'w')
        local = uname()[1]
        if local == 'cluster2':
            remote = 'node1'
        else:
            remote = None
        self.client = pm.MongoClient(remote)
        self.db = self.client.crystals
        if self.args.get('db') is None:
            self.repo = self.db.repo
            if not getcwd().startswith('/home/users/morris/structure_repository'):
                print('PERMISSION DENIED... and...')
                sleep(1)
                for i in range(100):
                    print('YOU DIDN\'T SAY THE MAGIC WORD')
                    sleep(0.01)
                print(80*'!')
                print('You shouldn\'t be importing to the main database from this folder!')
                print('Please use --db <YourDBName> to create a new collection,')
                print('or copy these files to the correct place!')
                print(80*'!')
                exit()
        else:
            if 'oqmd' in self.args['db']:
                exit('Cannot import directly to oqmd repo')
            elif len(self.args.get('db')) > 1:
                exit('Can only import to one collection.')
            else:
                self.repo = self.db[self.args.get('db')[0]]
        if not self.dryrun:
            # either drop and recreate or create spatula report collection
            self.db.spatula.drop()
            self.report = self.db.spatula
        # scan directory on init
        self.file_lists = self.scan_dir()
        # if import, as opposed to rebuild, scan for duplicates and remove from list
        if self.args['subcmd'] == 'import':
            self.file_lists = self.scan_dupes(self.file_lists)
        self.display_import(self.file_lists)
        # only create dicts if not just scanning
        if not self.scan:
            # convert to dict and db if required
            self.files2db(self.file_lists)
        if self.import_count == 0:
            print('No new structures imported!')
        if not self.dryrun and self.import_count > 0:
            print('Successfully imported', self.import_count, 'structures!')
            # index by enthalpy for faster/larger queries
            count = 0
            for entry in self.repo.list_indexes():
                count += 1
            # ignore default id index
            if count > 1:
                print('Index found, rebuilding...')
                self.repo.reindex()
            else:
                print('Building index...')
                self.repo.create_index([('enthalpy_per_atom', pm.ASCENDING)])
                self.repo.create_index([('stoichiometry', pm.ASCENDING)])
                self.repo.create_index([('cut_off_energy', pm.ASCENDING)])
                self.repo.create_index([('species_pot', pm.ASCENDING)])
                self.repo.create_index([('kpoints_mp_spacing', pm.ASCENDING)])
                self.repo.create_index([('xc_functional', pm.ASCENDING)])
                # index by source for rebuilds
                self.repo.create_index([('source', pm.ASCENDING)])
                print('Done!')
        elif self.dryrun:
            print('Dryrun complete!')
        if not self.scan:
            self.logfile.close()
        if not self.dryrun:
            # set log file to read only
            chmod(logfile_name, 0o550)
        if not self.scan:
            self.logfile = open(logfile_name, 'r')
            errors = sum(1 for line in self.logfile)
            if errors == 1:
                print('There is', errors, 'error to view in', logfile_name)
            elif errors == 0:
                print('There were no errors.')
            elif errors > 1:
                print('There are', errors, 'errors to view in', logfile_name)
            self.logfile.close()
        if not self.dryrun:
            # construct dictionary in spatula_report collection to hold info
            report_dict = dict()
            report_dict['last_modified'] = datetime.utcnow().replace(microsecond=0)
            report_dict['num_success'] = self.import_count
            report_dict['num_errors'] = errors
            report_dict['version'] = __version__
            self.report.insert_one(report_dict)

    def struct2db(self, struct):
        """ Insert completed Python dictionary into chosen
        database, with generated text_id. Add quality factor
        for any missing data.
        """
        try:
            plain_text_id = [self.wlines[randint(0, self.num_words-1)].strip(),
                             self.nlines[randint(0, self.num_nouns-1)].strip()]
            struct['text_id'] = plain_text_id
            if 'tags' in self.tag_dict:
                struct['tags'] = self.tag_dict['tags']
            struct['quality'] = 5
            # if any missing info at all, score = 0
            # include elem set for faster querying
            if 'elems' not in struct:
                struct['elems'] = list(set(struct['atom_types']))
            # del_list = []
            # for species in struct['species_pot']:
            # if species not in set(struct['atom_types']):
            # del_list.append(species)
            # for species in del_list:
            # del struct['species_pot'][species]
            if 'species_pot' not in struct:
                struct['quality'] = 0
            else:
                for elem in struct['stoichiometry']:
                    # remove all points for a missing pseudo
                    if 'species_pot' not in struct or elem[0] not in struct['species_pot']:
                        struct['quality'] = 0
                        break
                    else:
                        # remove a point for a generic OTF pspot
                        if 'OTF' in struct['species_pot'][elem[0]].upper():
                            struct['quality'] -= 1
            if 'xc_functional' not in struct:
                struct['quality'] = 0
            struct_id = self.repo.insert_one(struct).inserted_id
            root_src = [src for src in struct['source'] if
                        (src.endswith('.res') or src.endswith('.castep'))][0]
            self.struct_list.append((struct_id, root_src))
            self.manifest.write('+ {}\n'.format(root_src))
            if self.debug:
                print('Inserted', struct_id)
        except:
            # this shouldn't fail, but if it does, fail loudly but cleanly
            print_exc()
            return 0
        return 1

    def files2db(self, file_lists):
        """ Take all files found by scan and appropriately create dicts
        holding all available data; optionally push to database.
        """
        print('\n{:^52}'.format('###### RUNNING IMPORTER ######') + '\n')
        multi = False
        for root_ind, root in enumerate(file_lists):
            if root == '.':
                root_str = getcwd().split('/')[-1]
            else:
                root_str = root
            if self.verbosity > 0:
                print('Dictifying', root_str, '...')
            airss, cell, param, dir = 4*[False]
            if file_lists[root]['res_count'] > 0:
                if file_lists[root]['castep_count'] < file_lists[root]['res_count']:
                    if file_lists[root]['cell_count'] <= file_lists[root]['res_count']:
                        airss = True
            if airss:
                if file_lists[root]['param_count'] == 1:
                    param_dict, success = param2dict(file_lists[root]['param'][0],
                                                     debug=self.debug,
                                                     verbosity=self.verbosity)
                    param = success
                    if not success:
                        self.logfile.write(param_dict)
                elif file_lists[root]['param_count'] > 1:
                    if self.verbosity > 5:
                        print('Multiple param files found!')
                    multi = True
                if file_lists[root]['cell_count'] == 1:
                    cell_dict, success = cell2dict(file_lists[root]['cell'][0],
                                                   debug=self.debug,
                                                   verbosity=self.verbosity)
                    cell = success
                    if not success:
                        self.logfile.write(cell_dict)
                elif file_lists[root]['cell_count'] > 1:
                    multi = True
                    if self.verbosity > 5:
                        print('Multiple cell files found - ' +
                              'searching for param file with same name...')
                if multi:
                    for param_name in file_lists[root]['param']:
                        for cell_name in file_lists[root]['cell']:
                            if param_name.split('.')[0] in cell_name:
                                param_dict, success = param2dict(param_name,
                                                                 debug=self.debug,
                                                                 verbosity=self.verbosity)
                                param = success
                                if not success:
                                    self.logfile.write(param_dict)
                                cell_dict, success = cell2dict(cell_name,
                                                               debug=self.debug,
                                                               verbosity=self.verbosity)
                                cell = success
                                if not success:
                                    self.logfile.write(cell_dict)
                                if self.verbosity > 0:
                                    print('Found matching cell and param files:', param_name)
                                break
                # always try to scrape dir
                dir_dict, success = dir2dict(root)
                if not success:
                    self.logfile.write(dir_dict)
                dir = success
                # combine cell and param dicts for folder
                input_dict = dict()
                if dir:
                    input_dict = dir_dict.copy()
                if cell and param:
                    input_dict.update(cell_dict)
                    input_dict.update(param_dict)
                    input_dict['source'] = cell_dict['source'] + param_dict['source']
                    if dir:
                        input_dict['source'] = input_dict['source'] + dir_dict['source']
                else:
                    if dir:
                        input_dict = dir_dict.copy()
                        if cell:
                            input_dict.update(cell_dict)
                            input_dict['source'] = cell_dict['source'] + dir_dict['source']
                        elif param:
                            input_dict.update(param_dict)
                            input_dict['source'] = param_dict['source'] + dir_dict['source']
                # create res dicts and combine them with input_dict
                for ind, file in enumerate(file_lists[root]['res']):
                    if file.replace('.res', '.castep') in file_lists[root]['castep']:
                        struct_dict, success = castep2dict(file.replace('.res', '.castep'),
                                                           debug=self.debug,
                                                           dryrun=self.args.get('dryrun'),
                                                           verbosity=self.verbosity)
                    elif file.replace('.res', '.history') in file_lists[root]['castep']:
                        struct_dict, success = castep2dict(file.replace('.res', '.history'),
                                                           debug=self.debug,
                                                           dryrun=self.args.get('dryrun'),
                                                           verbosity=self.verbosity)
                    elif file.replace('.res', '.history.gz') in file_lists[root]['castep']:
                        struct_dict, success = castep2dict(file.replace('.res', '.history.gz'),
                                                           debug=self.debug,
                                                           dryrun=self.args.get('dryrun'),
                                                           verbosity=self.verbosity)
                    else:
                        struct_dict, success = res2dict(file,
                                                        debug=self.debug,
                                                        verbosity=self.verbosity)
                    if not success:
                        self.logfile.write(struct_dict)
                    else:
                        final_struct = input_dict.copy()
                        final_struct.update(struct_dict)
                        # calculate kpoint spacing if not found
                        if 'kpoints_mp_spacing' not in final_struct and \
                                'kpoints_mp_grid' in final_struct:
                            final_struct['kpoints_mp_spacing'] = calc_mp_spacing(
                                final_struct['lattice_cart'], final_struct['mp_grid'])
                        try:
                            final_struct['source'] = struct_dict['source'] + input_dict['source']
                        except:
                            pass
                        if not self.dryrun:
                            final_struct.update(self.tag_dict)
                            self.import_count += self.struct2db(final_struct)
            else:
                for ind, file in enumerate(file_lists[root]['castep']):
                    castep_dict, success = castep2dict(file,
                                                       debug=self.debug,
                                                       verbosity=self.verbosity)
                    if not success:
                        self.logfile.write(castep_dict)
                    else:
                        final_struct = castep_dict
                        if not self.dryrun:
                            final_struct.update(self.tag_dict)
                            self.import_count += self.struct2db(final_struct)
        for ind, file in enumerate(file_lists[root]['synth']):
                    synth_dict, success = synth2dict(file,
                                                     debug=self.debug,
                                                     verbosity=self.verbosity)
                    if not success:
                        self.logfile.write(synth_dict)
                    else:
                        if not self.dryrun:
                            synth_dict.update(self.tag_dict)
                            self.import_count += self.exp2db(synth_dict)
        for ind, file in enumerate(file_lists[root]['expt']):
                    expt_dict, success = expt2dict(file, debug=self.debug)
                    if not success:
                        self.logfile.write(expt_dict)
                    else:
                        if not self.dryrun:
                            expt_dict.update(self.tag_dict)
                            self.import_count += self.exp2db(expt_dict)

        if len(self.struct_list) > 0:
            self.update_changelog(self.repo.name, self.struct_list)

        return

    def update_changelog(self, collection_name: str, struct_list: list):
        """ Add a list of ObjectIds to a collection called
        __changelog_{collection_name}, storing "commits" that can be undone
        or reverted to.

        Input:

            | collection_name: str, the name of the base collection being imported to
            | struct_list : list((ObjectId, src)), list of (ObjectIds, source) of imported structures

        """
        changes = {'date': datetime.today(),
                   'count': len(struct_list),
                   'id_list': [struct[0] for struct in struct_list],
                   'src_list': [struct[1] for struct in struct_list]}
        self.db['__changelog_{}'.format(collection_name)].insert(changes)

    def scan_dir(self):
        """ Scans folder topdir recursively, returning list of
        CASTEP/AIRSS input/output files.
        """
        file_lists = dict()
        topdir = '.'
        topdir_string = getcwd().split('/')[-1]
        print('Scanning', topdir_string, 'for CASTEP/AIRSS output files... ',
              end='')
        for root, dirs, files in walk(topdir, followlinks=True, topdown=True):
            # get absolute path for rebuilds
            root = abspath(root)
            file_lists[root] = defaultdict(list)
            file_lists[root]['res_count'] = 0
            file_lists[root]['cell_count'] = 0
            file_lists[root]['param_count'] = 0
            file_lists[root]['castep_count'] = 0
            file_lists[root]['synth_count'] = 0
            file_lists[root]['expt_count'] = 0
            for file in files:
                file = root + '/' + file
                if self.verbosity > 0:
                    print(file)
                if file.endswith('.res'):
                    file_lists[root]['res'].append(file)
                    file_lists[root]['res_count'] += 1
                elif (file.endswith('.castep') or
                      file.endswith('.history') or
                      file.endswith('.history.gz')):
                    file_lists[root]['castep'].append(file)
                    file_lists[root]['castep_count'] += 1
                elif file.endswith('.cell'):
                    if file.endswith('-out.cell'):
                        continue
                    else:
                        file_lists[root]['cell'].append(file)
                        file_lists[root]['cell_count'] += 1
                elif file.endswith('.param'):
                    file_lists[root]['param'].append(file)
                    file_lists[root]['param_count'] += 1
                elif file.endswith('.synth'):
                    file_lists[root]['synth'].append(file)
                    file_lists[root]['synth_count'] += 1
                elif file.endswith('.expt'):
                    file_lists[root]['expt'].append(file)
                    file_lists[root]['expt_count'] += 1
        return file_lists

    def scan_dupes(self, file_lists):
        """ Scan the file_lists made by scan_dir and remove
        structures already in the database by matching sources.
        """
        new_file_lists = deepcopy(file_lists)
        for root_ind, root in enumerate(file_lists):
            # per folder delete list
            # do not import castep or res if seed name in db already
            castep_delete_list = []
            res_delete_list = []
            for file in new_file_lists[root]['castep']:
                count = self.repo.find({'source': {'$in': [file]}}).count()
                if self.debug:
                    print(count, file)
                if count >= 1:
                    castep_delete_list.append(file)
                    res_test = file.replace(file.split('.')[-1], 'res')
                    if res_test in new_file_lists[root]['res']:
                        res_delete_list.append(res_test)
                        new_file_lists[root]['res_count'] -= 1
                    new_file_lists[root]['castep_count'] -= 1
                if count > 1:
                    if self.debug:
                        print('Found double in database, this needs to be dealt with manually')
            for file in castep_delete_list:
                del new_file_lists[root]['castep'][new_file_lists[root]['castep'].index(file)]
            for file in res_delete_list:
                del new_file_lists[root]['res'][new_file_lists[root]['res'].index(file)]
            assert len(new_file_lists[root]['res']) == new_file_lists[root]['res_count'], \
                'res count does not match'
            assert len(new_file_lists[root]['castep']) == new_file_lists[root]['castep_count'], \
                'castep count does not match'
            # now delete just .res file names if already in db
            res_delete_list = []
            for file_ind, file in enumerate(new_file_lists[root]['res']):
                count = self.repo.find({'source': {'$in': [file]}}).count()
                if self.debug:
                    print(count, file)
                if count >= 1:
                    res_delete_list.append(file)
                    new_file_lists[root]['res_count'] -= 1
                if count > 1:
                    if self.debug:
                        print('Found double in database, this needs to be dealt with manually')
            for file in res_delete_list:
                del new_file_lists[root]['res'][new_file_lists[root]['res'].index(file)]
        return new_file_lists

    def display_import(self, file_lists):
        """ Display number of files to be imported and
        a breakdown of their types.
        """
        prefix = '\t\t'
        ResCount, CellCount, CastepCount, ParamCount = 4*[0]
        SynthCount, ExptCount = 2*[0]
        print('\n')
        for root in file_lists:
            RootResCount = file_lists[root]['res_count']
            RootCastepCount = file_lists[root]['castep_count']
            if RootResCount + RootCastepCount > 0 and self.debug:
                print(str(RootResCount+RootCastepCount), 'new structures found in', root)
            ResCount += RootResCount
            CastepCount += RootCastepCount
            CellCount += file_lists[root]['cell_count']
            ParamCount += file_lists[root]['param_count']
            CellCount += file_lists[root]['cell_count']
            ExptCount += file_lists[root]['expt_count']
            SynthCount += file_lists[root]['synth_count']
        print('\n\n')
        print(prefix, "{:8d}".format(ResCount), '\t\t.res files')
        print(prefix, "{:8d}".format(CastepCount), '\t\t.castep, .history or .history.gz files')
        print(prefix, "{:8d}".format(CellCount), '\t\t.cell files')
        print(prefix, "{:8d}".format(ParamCount), '\t\t.param files')
        print(prefix, "{:8d}".format(SynthCount), '\t\t.synth files')
        print(prefix, "{:8d}".format(ExptCount), '\t\t.expt files\n')
        return