#!/usr/bin/env python
# coding: utf-8
""" This file implements the matador command line functionality,
parsing user inputs and passing them to the CommandLine object.

"""

import argparse
import os
from sys import argv
from matador import __version__
from matador.cli import MatadorCommandLine


def main(testing=False):
    """ Parse all user args and construct a MatadorCommandLine object. """
    parser = argparse.ArgumentParser(
        prog='matador',
        description='MATerial and Atomic Database Of Refined structures.',
        epilog='Written and maintained by Matthew Evans (me388@cam.ac.uk) 2016-2017, version {}.'
        .format(__version__.strip()))
    parser.add_argument('--version', action='version', version='matador version ' + __version__ + '.')

    # define subparsers for subcommands
    subparsers = parser.add_subparsers(title='subcommands', description='valid sub-commands', dest='subcmd')

    # define parent parser for global arguments
    global_flags = argparse.ArgumentParser(add_help=False)

    # common arguments to all subcommands
    global_flags.add_argument('--db', nargs='+', help='choose which collection to query')
    global_flags.add_argument('--debug', action='store_true', help='enable debug printing throughout code.')
    global_flags.add_argument('-conf', '--config', type=str,
                              help='specify custom location of matador config file.'
                                   '(DEFAULT: $MATADOR_ROOT/config/matador_conf.json)')
    global_flags.add_argument('--devel', action='store_true', help='test devel code.')
    global_flags.add_argument('--profile', action='store_true', help='run code profiler.')
    global_flags.add_argument('-q', '--quiet', action='store_true', help='redirect most output to /dev/null.')

    # define all other flags by group
    structure_flags = argparse.ArgumentParser(add_help=False)
    structure_flags.add_argument('-c', '--composition', type=str, nargs='+',
                                 help='find all structures containing exclusively the given '
                                      'elements, e.g. LiSi. Macros defined for groups [I]-[VII] '
                                      '[Tran] [Lan] and [Act], used with square brackets.')
    structure_flags.add_argument('-int', '--intersection', action='store_true',
                                 help='query the intersection of compositions instead of the union '
                                      'e.g. -c LiSnS -int queries Li, Sn, S, LiSn, LiS & LiSnS.')
    structure_flags.add_argument('-n', '--num_species', type=int,
                                 help='find all structures containing a certain number of species.')
    structure_flags.add_argument('-f', '--formula', type=str, nargs='+',
                                 help='query a particular chemical formula, e.g. GeTeSi3')
    structure_flags.add_argument('-i', '--id', type=str, nargs='+',
                                 help='specify a particular structure by its text_id')
    structure_flags.add_argument('-ac', '--calc_match', action='store_true',
                                 help='display calculations of the same accuracy as specified id')
    structure_flags.add_argument('-kpttol', '--kpoint-tolerance', type=float,
                                 help='kpoint tolerance for calculation matches (DEFAULT: +/- 0.01 1/Å)')
    structure_flags.add_argument('-z', '--num_fu', type=int,
                                 help='query a calculations with more than n formula units')
    structure_flags.add_argument('-sg', '--space_group', help='query a particular space group')
    structure_flags.add_argument('-u', '--uniq', type=float, nargs='?', const=0.1,
                                 help='float, return only unique structures (filtered by PDF '
                                      'overlap), to this tolerance (DEFAULT: 0.1)')
    structure_flags.add_argument('-p', '--pressure', type=float,
                                 help='specify an isotropic external pressure to search for, e.g. 10 (GPa)')
    structure_flags.add_argument('-pf', '--partial-formula', action='store_true',
                                 help='stoichiometry/composition queries will include other unspecified species, e.g. '
                                      '-pf search for Li will query any structure containing Li, not just pure Li.')
    structure_flags.add_argument('--tags', nargs='+', type=str, help=('search for manual tags'))
    structure_flags.add_argument('--doi', type=str, help=('search for DOI in format xxxx/xxxx'))
    structure_flags.add_argument('-icsd', '--icsd', type=int, const=0, nargs='?', help=('search for an ICSD CollCode'))
    structure_flags.add_argument('-ss', '--src_str', type=str,
                                 help=('search for a string inside the structure sources'))
    structure_flags.add_argument('-root', '--root_src', type=str,
                                 help=('search for a root_source string of the structure'))
    structure_flags.add_argument('-encap', '--encapsulated', action='store_true',
                                 help='query only structures encapsulated in a carbon nanotube.')
    structure_flags.add_argument('-cntr', '--cnt_radius', type=float,
                                 help='specify the radius of the encapsulating nanotube to within 0.01 Å')
    structure_flags.add_argument('-cntv', '--cnt_vector', type=int, nargs='+',
                                 help='specify the chiral vector of the encapsulating nanotube')
    structure_flags.add_argument('-ecut', '--cutoff', type=float, nargs='+',
                                 help='specify the min. and optionally max. planewave cutoff.')
    structure_flags.add_argument('-geom', '--geom_force_tol', type=float, nargs='+',
                                 help='force tolerance in eV/Å to query for calc matches.')
    structure_flags.add_argument('--sedc', type=str, help='specify the dispersion correction scheme, e.g. TS or null.')
    structure_flags.add_argument('-xc', '--xc_functional', type=str,
                                 help='specify an xc-functional to query (case-insensitive).')
    structure_flags.add_argument('-kpts', '--mp_spacing', type=float,
                                 help='specify an MP grid spacing in 2π/Å units, e.g. 0.05, will return all values '
                                      'structures with value within --kpt_tol')
    structure_flags.add_argument('--spin', type=str,
                                 help='specifiy whether to query non-spin-polarized (0) calcs or spin polarized calcs '
                                      '(!=1), or lump them both together with `any`')
    structure_flags.add_argument('--loose', action='store_true',
                                 help='loosely matches with calc_match, i.e. only matches pspot and xc_functional')
    structure_flags.add_argument('--ignore_warnings', action='store_true', help='includes possibly bad structures')
    structure_flags.add_argument('--filter', type=str,
                                 help='specify a simple float field to filter. Requires --values')
    structure_flags.add_argument('--values', nargs='+', type=float,
                                 help='specify the minimum floats, or [min, max] values of field')

    material_flags = argparse.ArgumentParser(add_help=False)
    material_flags.add_argument('-hc', '--hull_cutoff', type=float,
                                help='return only structures within a certain distance from hull in eV/atom')
    material_flags.add_argument('-hT', '--hull_temp', type=float,
                                help='return only structures within a certain distance from hull in K')
    material_flags.add_argument('--biggest', action='store_true',
                                help='use the largest subset of structures to create a hull')
    material_flags.add_argument('--volume', action='store_true',
                                help='plot a volume curve from convex hull (currently limited to binaries)')
    material_flags.add_argument('--chempots', type=float, nargs='+',
                                help='manually specify chem pots as enthalpy per atom for a rough hull.')

    plot_flags = argparse.ArgumentParser(add_help=False)
    plot_flags.add_argument('--pdf', action='store_true', help='save pdf rather than showing plot in X')
    plot_flags.add_argument('--png', action='store_true', help='save png rather than showing plot in X')
    plot_flags.add_argument('--csv', action='store_true', help='save plotting data to separate csv files')
    plot_flags.add_argument('--labels', action='store_true', help='label hull plots')
    plot_flags.add_argument('--svg', action='store_true', help='save svg rather than showing plot in X')
    plot_flags.add_argument('--subplot', action='store_true', help='plot combined hull and voltage graph')
    plot_flags.add_argument('--no_plot', action='store_true', help='suppress plotting')
    plot_flags.add_argument('--capmap', action='store_true', help='plot heat map of gravimetric capacity')
    plot_flags.add_argument('--sampmap', action='store_true', help='plot heat map of concentration sampling')
    plot_flags.add_argument('--efmap', action='store_true', help='plot heat map of formation energy')
    plot_flags.add_argument('--pathways', action='store_true',
                            help='plot line from stable B_x C_y to pure A in ABC ternary.')
    plot_flags.add_argument('--expt', type=str, help='enter experimental voltage curve .csv file for plotting.')
    plot_flags.add_argument('--expt_label', type=str, help='label for experimental data on voltage curve.')

    spatula_flags = argparse.ArgumentParser(add_help=False)
    spatula_flags.add_argument('-d', '--dryrun', action='store_true',
                               help='run the importer without connecting to the database')
    spatula_flags.add_argument('-v', '--verbosity', action='count', help='enable verbose output')
    spatula_flags.add_argument('-t', '--tags', nargs='+', type=str, help='set user tags, e.g. nanotube, project name')
    spatula_flags.add_argument('-s', '--scan', action='store_true',
                               help='only scan the database for new structures, do not dictify')

    changes_flags = argparse.ArgumentParser(add_help=False)
    changes_flags.add_argument('-c', '--changeset', type=int, help='changeset number to query')
    changes_flags.add_argument('-r', '--revert', type=int, help='revert database to specified changeset')
    changes_flags.add_argument('-u', '--undo', action='store_true', help='undo changeset')

    collection_flags = argparse.ArgumentParser(add_help=False)
    collection_flags.add_argument('--to', type=str, help='the text_id of a structure with the desired parameters')
    collection_flags.add_argument('--with', type=str,
                                  help=('the seedname (must be within pwd) of cell and param ' +
                                        'files to use for polishing/swaps'))
    collection_flags.add_argument('--prefix', type=str,
                                  help='add a prefix to all file names to write out (auto-appended with an underscore')

    query_flags = argparse.ArgumentParser(add_help=False)

    query_flags.add_argument('-s', '--summary', action='store_true',
                             help='show only the ground state for each stoichiometry.')
    query_flags.add_argument('-t', '--top', type=int, help='number of structures to show/write (DEFAULT: 10)')
    query_flags.add_argument('-dE', '--delta_E', type=float,
                             help='maximum distance from ground state structure to show/write in eV/atom')
    query_flags.add_argument('-d', '--details', action='store_true',
                             help='show as much detail about calculation as possible')
    query_flags.add_argument('-pa', '--per_atom', action='store_true', help='show quantities per atom not per fu.')
    query_flags.add_argument('--source', action='store_true',
                             help='print filenames from which structures were wrangled')
    query_flags.add_argument('-v', '--view', action='store_true',
                             help='quickly view a structure/structures with ase-gui')
    query_flags.add_argument('--cell', action='store_true',
                             help='export query to .cell files in folder name from query string')
    query_flags.add_argument('--param', action='store_true',
                             help='export query to .param files in folder name from query string')
    query_flags.add_argument('--res', action='store_true',
                             help='export query to .res files in folder name from query string')
    query_flags.add_argument('--pdb', action='store_true',
                             help='export query to .pdb files in folder name from query string')
    query_flags.add_argument('--xsf', action='store_true',
                             help='export query to .xsf files in folder name from query string')
    query_flags.add_argument('--markdown', action='store_true', help='export query summary to a markdown file')
    query_flags.add_argument('--latex', action='store_true', help='export query summary to a LaTeX table')
    query_flags.add_argument('--write_n', type=int, help='export only those structures with n species')

    swap_flags = argparse.ArgumentParser(add_help=False)
    swap_flags.add_argument('-sw', '--swap', type=str, nargs='+',
                            help='swap all atoms in structures from a query from the first n-1 species to the nth, '
                                 'e.g. -sw NAs will swap all N to As, -sw NAs:LiNa will swap all N to As, and all Li '
                                 'to Na, and -sw [V]As:[Li,K,Rb]Na will swap all group V elements to As and all of Li,'
                                 'K and Rb to Na.')
    diff_flags = argparse.ArgumentParser(add_help=False)
    diff_flags.add_argument('-cmp', '--compare', type=str, nargs='+',
                            help='diff phase diagrams between two different times, in standard time format, '
                                 'e.g. `--compare 1y2m5d3h` will compare the present hull with that of 1 year, 2 '
                                 'months, 5 days and 3 hours ago, and `--compare 3d 2d` will compare three days ago '
                                 'to two days ago.')
    pdffit_flags = argparse.ArgumentParser(add_help=False)
    pdffit_flags.add_argument('-file', '--file', type=str, help='experimental input file to fit structures to.')
    pdffit_flags.add_argument('-min', '--xmin', type=float,
                              help='minimum value to compute the PDF (DEFAULT: 1 Angstrom)')
    pdffit_flags.add_argument('-max', '--xmax', type=float,
                              help='maximum value to compute the PDF (DEFAULT: 50 Angstrom')
    pdffit_flags.add_argument('-dx', '--dx', type=float, help='spacing to compute PDF at')
    pdffit_flags.add_argument('-2', '--two_phase', type=float, help='fit two phases to experimental PDF')
    pdffit_flags.add_argument('-np', '--num_processes', type=int, help='number of concurrent fits to perform.')

    refine_flags = argparse.ArgumentParser(add_help=False)
    refine_flags.add_argument('-task', '--task', type=str, help='refine subtask to perform: options are spg or sub')
    refine_flags.add_argument('-mode', '--mode', type=str,
                              help='mode of refinement: options are display, set and overwrite')
    refine_flags.add_argument('-symprec', '--symprec', type=float, help='spglib symmetry precision for refinement')
    refine_flags.add_argument('--new_tag', type=str, help='new tag to add to structures in query')
    refine_flags.add_argument('--new_doi', type=str, help='new doi to add to structures in query')

    stats_flags = argparse.ArgumentParser(add_help=False)
    stats_flags.add_argument('-l', '--list', action='store_true', help='list all collections, their sizes, and owners')
    stats_flags.add_argument('--delete', action='store_true', help='try to delete collection specified by --db')

    # define subcommand parsers and their arguments

    # matador stats
    subparsers.add_parser('stats', help='print some stats about the database.', parents=[global_flags, stats_flags])

    # matador query
    subparsers.add_parser('query',
                          help='query and extract structures from the database',
                          parents=[global_flags, query_flags, structure_flags])

    # matador import
    subparsers.add_parser('import',
                          help='import new structures in folder into database',
                          parents=[global_flags, spatula_flags])

    # matador pdffit
    subparsers.add_parser('pdffit',
                          help='provide experimental .gr file and fit to calculated PDF of structures in query',
                          parents=[global_flags, query_flags, material_flags,
                                   structure_flags, pdffit_flags])

    # matador hull
    subparsers.add_parser('hull',
                          help='create a convex hull from query results (currently limited to binaries and ternaries)',
                          parents=[global_flags, structure_flags,
                                   material_flags, plot_flags, query_flags])

    # matador voltage
    subparsers.add_parser('voltage',
                          help='plot a voltage curve from query results (currently limited to binaries and ternaries)',
                          parents=[global_flags, structure_flags,
                                   material_flags, plot_flags, query_flags])

    # matador changes
    subparsers.add_parser('changes',
                          help='view database changelog or undo additions to database (NB: not deletions!)',
                          parents=[global_flags, changes_flags])

    # matador hulldiff
    subparsers.add_parser('hulldiff',
                          help='diff two convex hulls with the --compare flag.',
                          parents=[global_flags, structure_flags,
                                   material_flags, plot_flags, query_flags, diff_flags])

    # matador swaps
    subparsers.add_parser('swaps',
                          help='perform atomic swaps on query results',
                          parents=[global_flags, collection_flags, query_flags,
                                   structure_flags, material_flags, swap_flags])

    # matador refine
    subparsers.add_parser('refine',
                          help='update structures in the database according to specified --task',
                          parents=[global_flags, query_flags, structure_flags,
                                   refine_flags, material_flags])

    parsed_args = parser.parse_args()

    # check for inconsistent argument combinations
    if vars(parsed_args).get('intersection') and vars(parsed_args).get('composition') is None:
        raise SystemExit('--intersection requires --composition.')
    if vars(parsed_args).get('subcmd') == 'stats' and vars(parsed_args).get('list') and vars(parsed_args).get(
            'delete'):
        raise SystemExit('Cannot use -l/--list and --delete')
    # if vars(parsed_args).get('formula') and vars(parsed_args).get('composition'):
    # raise SystemExit('Cannot use -f/--formula and -c/--composition together.')
    if vars(parsed_args).get('filter') and vars(parsed_args).get('values') is None:
        raise SystemExit('--filter requires --values.')
    if vars(parsed_args).get('values') and vars(parsed_args).get('filter') is None:
        print('Ignoring redundant supplied values...')
    if vars(parsed_args).get('subcmd') == 'hull' and vars(parsed_args).get('composition') is None:
        raise SystemExit('hull requires --composition')
    if vars(parsed_args).get('subcmd') == 'pdffit':
        if vars(parsed_args).get('file') is None:
            raise SystemExit('pdffit requires specified --file, exiting...')
        if not os.path.isfile(vars(parsed_args).get('file')):
            raise SystemExit('specified --file does not exist, exiting...')
    if vars(parsed_args).get('hull_cutoff') and vars(parsed_args).get('hull_temp'):
        raise SystemExit('hull_cutoff and hull_temp both specified, exiting...')
    if vars(parsed_args).get('calc_match') and vars(parsed_args).get('id') is None:
        raise SystemExit('calc_match requires specification of a text_id with -i, exiting...')
    if vars(parsed_args).get('profile'):
        import cProfile
        import pstats
        from sys import version_info
        profiler = cProfile.Profile()
        profiler.enable()

    MatadorCommandLine(parsed_args, argstr=argv[1:], testing=testing)

    if vars(parsed_args).get('profile'):
        profiler.disable()
        fname = 'matador-{}-{}.{}.{}'.format(__version__, version_info.major, version_info.minor, version_info.micro)
        profiler.dump_stats(fname + '.prof')
        with open(fname + '.pstats', 'w') as fp:
            stats = pstats.Stats(profiler, stream=fp).sort_stats('cumulative')
            stats.print_stats()


if __name__ == '__main__':
    main()