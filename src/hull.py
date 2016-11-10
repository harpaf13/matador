# coding: utf-8
""" This file implements convex hull functionality
from database queries.
"""

from __future__ import print_function
from scipy.spatial import ConvexHull
from traceback import print_exc
from bson.son import SON
from bisect import bisect_left
from print_utils import print_failure, print_notify, print_warning
from chem_utils import get_capacities, get_molar_mass, get_num_intercalated
from cursor_utils import set_cursor_from_array, get_array_from_cursor
from export import generate_hash, generate_relevant_path
from glmol_wrapper import get_glmol_placeholder_string
import pymongo as pm
import re
import numpy as np
from mpldatacursor import datacursor
import matplotlib.pyplot as plt
import matplotlib.colors as colours
import ternary


class QueryConvexHull():
    """ Implements a Convex Hull for formation energies
    from a fryan DBQuery.
    """
    def __init__(self, query, subcmd='hull', **kwargs):
        """ Accept query from fryan as argument. """
        self.args = kwargs
        if self.args.get('subcmd') is None:
            self.args['subcmd'] = subcmd
        self.query = query
        self.cursor = list(query.cursor)
        self.K2eV = 8.61733e-5

        if self.args.get('hull_temp') is not None:
            self.hull_cutoff = float(self.args['hull_temp']*self.K2eV)
        elif self.args.get('hull_cutoff') is not None:
            self.hull_cutoff = float(self.args['hull_cutoff'])
        else:
            self.hull_cutoff = 0.0

        if self.args.get('chempots') is not None:
            self.chem_pots = self.args.get('chempots')
            for ind, pot in enumerate(self.chem_pots):
                if pot > 0:
                    self.chem_pots[ind] = -1*self.chem_pots[ind]
        else:
            self.chem_pots = None

        self.hull_2d()

        if len(self.hull_cursor) == 0:
            print_warning('No structures on hull with chosen chemical potentials.')
        else:
            if self.args.get('hull_temp'):
                print_notify(str(len(self.hull_cursor)) + ' structures within ' +
                             str(self.args.get('hull_temp')) +
                             ' K of the hull with chosen chemical potentials.')
            else:
                print_notify(str(len(self.hull_cursor)) + ' structures within ' +
                             str(self.hull_cutoff) +
                             ' eV of the hull with chosen chemical potentials.')

        self.query.display_results(self.hull_cursor, hull=True)

        if self.args['subcmd'] == 'voltage':
            if self.args.get('debug'):
                self.set_plot_param()
                self.voltage_curve()
                # self.metastable_voltage_profile()
            else:
                self.voltage_curve()
                self.set_plot_param()
                if self.args.get('subplot'):
                    self.subplot_voltage_hull()
                else:
                    self.plot_voltage_curve()
                self.plot_2d_hull()
        elif self.args.get('volume'):
            self.volume_curve()

        if self.args['subcmd'] == 'hull' and not self.args.get('no_plot'):
            if self.args.get('bokeh'):
                self.plot_2d_hull_bokeh()
            else:
                self.set_plot_param()
                if len(self.elements) == 3:
                    self.plot_3d_ternary_hull()
                    self.plot_ternary_hull()
                else:
                    self.plot_2d_hull()
            if self.args.get('volume'):
                self.plot_volume_curve()

    def get_chempots(self):
        """ Search for chemical potentials that match
        the structures in the query cursor,
        and add them to the cursor.
        """
        query = self.query
        self.mu_enthalpy = np.zeros((2))
        self.mu_volume = np.zeros((2))
        query_dict = dict()
        if self.chem_pots is not None:
            self.fake_chempots()
        else:
            print(60*'─')
            self.match = len(self.elements)*[None]
            # scan for suitable chem pots in database
            for ind, elem in enumerate(self.elements):
                print('Scanning for suitable', elem, 'chemical potential...')
                query_dict['$and'] = list(query.calc_dict['$and'])
                query_dict['$and'].append(query.query_quality())
                query_dict['$and'].append(query.query_composition(custom_elem=[elem]))
                # if oqmd, only query composition, not parameters
                if query.args.get('tags') is not None:
                    query_dict['$and'].append(query.query_tags())
                mu_cursor = query.repo.find(SON(query_dict)).sort('enthalpy_per_atom',
                                                                  pm.ASCENDING)
                try:
                    self.match[ind] = mu_cursor[0]
                except:
                    self.match[ind] = None
                if self.match[ind] is not None:
                    if ind == 0:
                        self.mu_enthalpy[ind] = float(self.match[ind]['enthalpy_per_atom'])
                        self.mu_volume[ind] = float(self.match[ind]['cell_volume'] /
                                                    self.match[ind]['num_atoms'])
                    else:
                        self.mu_enthalpy[1] += float(self.match[ind]['enthalpy_per_atom'])
                        self.mu_volume[1] = float(self.match[ind]['cell_volume'] /
                                                  self.match[ind]['num_atoms'])
                    print('Using', ''.join([self.match[ind]['text_id'][0], ' ',
                          self.match[ind]['text_id'][1]]), 'as chem pot for', elem)
                    print(60*'─')
                else:
                    print_failure('No possible chem pots found for ' + elem + '.')
                    exit()
            for i, mu in enumerate(self.match):
                self.match[i]['hull_distance'] = 0.0
                self.match[i]['enthalpy_per_b'] = mu['enthalpy_per_atom']
                self.match[i]['num_a'] = 0
            self.match[0]['num_a'] = float('inf')
            self.cursor.insert(0, self.match[0])
            for match in self.match[1:]:
                self.cursor.append(match)
        return

    def fake_chempots(self):
        """ Spoof documents for command-line
        chemical potentials.
        """
        self.match = [dict(), dict()]
        for i, mu in enumerate(self.match):
            self.mu_enthalpy[i] = self.chem_pots[i]
            self.match[i]['enthalpy_per_atom'] = self.mu_enthalpy[i]
            self.match[i]['enthalpy'] = self.mu_enthalpy[i]
            self.match[i]['num_fu'] = 1
            self.match[i]['text_id'] = ['command', 'line']
            self.match[i]['stoichiometry'] = [[self.elements[i], 1]]
            self.match[i]['space_group'] = 'xxx'
            self.match[i]['hull_distance'] = 0.0
            self.match[i]['enthalpy_per_b'] = self.match[i]['enthalpy_per_atom']
            self.match[i]['num_a'] = 0
        self.match[0]['num_a'] = float('inf')
        notify = ('Using custom energies of ' + str(self.mu_enthalpy[0]) + ' eV/atom ' +
                  'and ' + str(self.mu_enthalpy[1]) + ' eV/atom as chemical potentials.')
        print(len(notify)*'─')
        print(notify)
        print(len(notify)*'─')

    def get_atoms_per_fu(self, doc):
        """ Calculate the number of atoms per formula unit. """
        atoms_per_fu = 0
        for j in range(len(doc['stoichiometry'])):
            atoms_per_fu += doc['stoichiometry'][j][1]
        return atoms_per_fu

    def get_formation_energy(self, doc):
        """ From given chemical potentials, calculate the simplest
        formation energy of the desired document.
        """
        formation = doc['enthalpy_per_atom']
        for mu in self.match:
            for j in range(len(doc['stoichiometry'])):
                if mu['stoichiometry'][0][0] == doc['stoichiometry'][j][0]:
                    formation -= (mu['enthalpy_per_atom'] * doc['stoichiometry'][j][1] /
                                  self.get_atoms_per_fu(doc))
        return formation

    def get_concentration(self, doc):
        """ Returns x for A_x B_{1-x}
        or xyz for A_x B_y C_z, (x+y+z=1). """
        stoich = [0.0] * (len(self.elements)-1)
        for ind, elem in enumerate(doc['stoichiometry']):
            if elem[0] in self.elements[:-1]:
                stoich[self.elements.index(elem[0])] = elem[1]/float(self.get_atoms_per_fu(doc))
        return stoich

    def get_array_from_cursor(self, cursor, key):
        """ Returns a numpy array of the values of a key
        in a cursor.
        """
        array = []
        try:
            for doc in cursor:
                array.append(doc[key])
        except:
            print_exc()
        array = np.asarray(array)
        assert(len(array) == len(cursor))
        return array

    def set_cursor_from_array(self, array, key):
        """ Updates the key-value pair for documents in
        internal cursor from a numpy array.
        """
        assert(len(array) == len(self.cursor) or len(array) - 1 == len(self.cursor))
        for ind, doc in enumerate(self.cursor):
            self.cursor[ind][key] = array[ind]
        return

    def get_hull_distances(self, structures):
        """ Returns array of hull distances. """
        tie_line_comp = self.structure_slice[self.hull.vertices, 0]
        tie_line_energy = self.structure_slice[self.hull.vertices, -1]
        tie_line_comp = np.asarray(tie_line_comp)
        tie_line_energy = tie_line_energy[np.argsort(tie_line_comp)]
        tie_line_comp = tie_line_comp[np.argsort(tie_line_comp)]
        # if only chem pots on hull, dist = energy
        if len(self.structure_slice) == 2:
            hull_dist = np.ones((len(structures)))
            hull_dist = structures[:, -1]
        # if only binary hull, do binary search
        elif len(self.structure_slice[0]) == 2:
            hull_dist = np.ones((len(structures)))
            for ind in range(len(structures)):
                # get the index of the next stoich on the hull from the current structure
                i = bisect_left(tie_line_comp, structures[ind, 0])
                energy_pair = (tie_line_energy[i-1], tie_line_energy[i])
                comp_pair = (tie_line_comp[i-1], tie_line_comp[i])
                # calculate equation of line between the two
                gradient = (energy_pair[1] - energy_pair[0]) / (comp_pair[1] - comp_pair[0])
                intercept = ((energy_pair[1] + energy_pair[0]) -
                             gradient * (comp_pair[1] + comp_pair[0])) / 2
                # calculate hull_dist
                hull_dist[ind] = structures[ind, -1] - (gradient * structures[ind, 0] + intercept)
        # otherwise, set to zero until proper N-d distance can be implemented
        else:
            hull_dist = np.ones((len(structures)+1))
            for ind in self.hull.vertices:
                hull_dist[ind] = 0.0
        
        return hull_dist, tie_line_energy, tie_line_comp

    def get_text_info(self, cursor=None, hull=False, html=False):
        """ Grab textual info for plot labels. """
        info = []
        if cursor is None:
            cursor = self.cursor
        if hull:
            stoich_strings = []
        for ind, doc in enumerate(cursor):
            stoich_string = ''
            for elem in doc['stoichiometry']:
                stoich_string += elem[0]
                stoich_string += '$_{' + str(elem[1]) + '}$' if elem[1] != 1 else ''
            if hull:
                if stoich_string not in stoich_strings:
                    stoich_strings.append(stoich_string)
            info_string = "{0:^10}\n{1:^24}\n{2:^5s}\n{3:.3f} eV".format(stoich_string,
                                                                        doc['text_id'][0] + ' ' + doc['text_id'][1],
                                                                        doc['space_group'],
                                                                        doc['hull_distance'])
            if html:
                for char in ['$', '_', '{', '}']:
                    info_string = info_string.replace(char, '')
                info_string = info_string.split('\n')
            info.append(info_string)
        if hull:
            info = stoich_strings
        return info

    def hull_2d(self, dis=False):
        """ Create a convex hull for two elements. """
        query = self.query
        self.elements = query.args.get('composition')
        self.elements = [elem for elem in re.split(r'([A-Z][a-z]*)', self.elements[0]) if elem]
        assert(len(self.elements) < 4 and len(self.elements) > 1)
        ternary = False
        if len(self.elements) == 3:
            ternary = True
        self.get_chempots()
        if ternary:
            print('Constructing ternary hull...')
            if not self.args.get('intersection'):
                print_warning('Please query with -int/--intersection when creating ternary hulls.')
                exit('Exiting...')
        else:
            print('Constructing binary hull...')
        # define hull by order in command-line arguments
        self.x_elem = [self.elements[0]]
        self.one_minus_x_elem = list(self.elements[1:])
        one_minus_x_elem = self.one_minus_x_elem
        # grab relevant information from query results; also make function?
        for ind, doc in enumerate(self.cursor):
            if not ternary:
                # calculate number of atoms of type B per formula unit
                nums_b = len(one_minus_x_elem)*[0]
                for elem in doc['stoichiometry']:
                    for chem_pot_ind, chem_pot in enumerate(one_minus_x_elem):
                        if elem[0] == chem_pot:
                            nums_b[chem_pot_ind] += elem[1]
                num_b = sum(nums_b)
                num_fu = doc['num_fu']
                # get enthalpy and volume per unit B
                if num_b == 0:
                    self.cursor[ind]['enthalpy_per_b'] = 12345e5
                    self.cursor[ind]['cell_volume_per_b'] = 12345e5
                else:
                    self.cursor[ind]['enthalpy_per_b'] = doc['enthalpy'] / (num_b*num_fu)
                    self.cursor[ind]['cell_volume_per_b'] = doc['cell_volume'] / (num_b*num_fu)
            self.cursor[ind]['formation_enthalpy_per_atom'] = self.get_formation_energy(doc)
            self.cursor[ind]['concentration'] = self.get_concentration(doc)
        # create stacked array of hull data
        structures = np.hstack((get_array_from_cursor(self.cursor, 'concentration'),
                                get_array_from_cursor(self.cursor, 'formation_enthalpy_per_atom').reshape(len(self.cursor), 1)))
        # create hull with SciPy routine, including only points with formation energy < 0
        if ternary:
            self.structure_slice = structures#[np.where(structures[:, -1] <= 0 + 1e-9)]
            # self.structure_slice[np.where(structures[:, -1] <= 0 + 1e-9)][-1] = 10
            self.structure_slice = np.vstack((self.structure_slice, np.array([0,0,1e5])))
        else:
            self.structure_slice = structures[np.where(structures[:, -1] <= 0 + 1e-9)]
        if len(self.structure_slice) == 2:
            self.hull = FakeHull()
            self.hull_dist, self.hull_energy, self.hull_comp = self.get_hull_distances(structures)
            # should add chempots only to hull_cursor
            set_cursor_from_array(self.cursor, self.hull_dist, 'hull_distance')
        else:
            try:
                self.hull = ConvexHull(self.structure_slice)
                # filter out top of hull - ugly
                if ternary:
                    temp = [vertex for vertex in self.hull.vertices if self.structure_slice[vertex, -1] <= 0 + 1e-9]
                    del self.hull
                    self.hull = FakeHull()
                    self.hull.vertices = list(temp)
                self.hull_dist, self.hull_energy, self.hull_comp = self.get_hull_distances(structures)
                if ternary:
                    self.hull_dist = self.hull_dist[:-1]
                set_cursor_from_array(self.cursor, self.hull_dist, 'hull_distance')
            except:
                print_exc()
                print('Error with QHull, plotting points only...')

        try: 
            self.info = self.get_text_info(html=self.args.get('bokeh'))
            self.hull_info = self.get_text_info(cursor=self.hull_cursor, hull=True, html=self.args.get('bokeh'))
        except:
            pass
        if not ternary:
            Q = get_capacities(get_num_intercalated(self.cursor), get_molar_mass(self.elements[1]))
            set_cursor_from_array(self.cursor, Q, 'gravimetric_capacity')
        self.hull_cursor = [self.cursor[idx] for idx in np.where(self.hull_dist <= self.hull_cutoff + 1e-12)[0]]
        self.structures = structures

    def voltage_curve(self):
        """ Take convex hull and calculate voltages. """
        print('Generating voltage curve...')
        mu_enthalpy = get_array_from_cursor(self.match, 'enthalpy_per_atom')
        x = get_num_intercalated(self.hull_cursor)
        # sort for voltage calculation
        Q = get_capacities(x, get_molar_mass(self.elements[1]))
        # set_cursor_from_array(self.hull_cursor, Q, 'gravimetric_capacity')
        Q = Q[np.argsort(x)]
        stable_enthalpy_per_b = get_array_from_cursor(self.hull_cursor, 'enthalpy_per_b')[np.argsort(x)]
        print(stable_enthalpy_per_b)
        x = np.sort(x)
        x, uniq_idxs = np.unique(x, return_index=True)
        stable_enthalpy_per_b = stable_enthalpy_per_b[uniq_idxs]
        Q = Q[uniq_idxs]
        V = []
        # for i in range(len(x)-1, 0, -1):
        for i in range(len(x)):
            V.append(-(stable_enthalpy_per_b[i] - stable_enthalpy_per_b[i-1]) /
                      (x[i] - x[i-1]) +
                      (mu_enthalpy[0]))
        V[0] = V[1]
        # x = np.append([0], x)
        # Q = np.append([0], Q)
        # make V, Q and x available for plotting
        self.voltages = V
        self.Q = Q
        self.x = x
        print(zip(self.Q, self.x, self.voltages))
        return

    def volume_curve(self):
        """ Take stable compositions and volume and calculate
        volume expansion per "B" in AB binary.
        """
        stable_comp = get_array_from_cursor(self.hull_cursor, 'concentration')
        stable_vol = get_array_from_cursor(self.hull_cursor, 'cell_volume_per_b')
        # here, in A_x B_y
        x = []
        # and v is the volume per x atom
        v = []
        for i in range(len(stable_comp)):
            x.append(stable_comp[i]/(1-stable_comp[i]))
            v.append(stable_vol[i])
        self.x = x
        self.vol_per_y = v
        return

    def plot_2d_hull(self, dis=False):
        """ Plot calculated hull. """
        if self.args.get('pdf') or self.args.get('png') or self.args.get('svg'):
            fig = plt.figure(facecolor=None, figsize=(5, 4))
        else:
            fig = plt.figure(facecolor=None)
        ax = fig.add_subplot(111)
        scatter = []
        hull_scatter = []
        x_elem = [self.elements[0]]
        one_minus_x_elem = list(self.elements[1:])
        plt.draw()
        # star structures on hull
        if len(self.structure_slice) != 2:
            for ind in range(len(self.hull.vertices)):
                if self.structure_slice[self.hull.vertices[ind], 1] <= 0:
                    hull_scatter.append(ax.scatter(self.structure_slice[self.hull.vertices[ind], 0],
                                                   self.structure_slice[self.hull.vertices[ind], 1],
                                                   c=self.colours[1],
                                                   marker='o', zorder=99999, edgecolor='k',
                                                   s=self.scale*40, lw=1.5, alpha=1,
                                                   label=self.info[self.hull.vertices[ind]]))
                # ax.annotate(self.hull_info[ind],
                            # xy=(self.structure_slice[self.hull.vertices[ind], 0],
                                # self.structure_slice[self.hull.vertices[ind], 1]),
                            # textcoords='data',
                            # ha='center',
                            # zorder=99999,
                            # xytext=(self.structure_slice[self.hull.vertices[ind], 0],
                                    # self.structure_slice[self.hull.vertices[ind], 1]-0.05))
            lw = self.scale * 0 if self.mpl_new_ver else 1
            # points for off hull structures
            if self.hull_cutoff == 0:
                # if no specified hull cutoff, ignore labels and colour
                # by distance from hull
                cmap_full = plt.cm.get_cmap('Dark2')
                cmap = colours.LinearSegmentedColormap.from_list(
                    'trunc({n},{a:.2f},{b:.2f})'.format(n=cmap_full.name, a=0, b=1),
                    cmap_full(np.linspace(0.15, 0.4, 100)))
                # scatter = ax.scatter(self.structures[:, 0], self.structures[:, 1],
                                     # s=self.scale*40, lw=lw, alpha=0.9,
                                     # c=self.hull_dist,
                                     # edgecolor='k', zorder=300, cmap=cmap)
                scatter = ax.scatter(self.structures[np.argsort(self.hull_dist), 0][::-1],
                                     self.structures[np.argsort(self.hull_dist), -1][::-1],
                                     s=self.scale*40, lw=lw, alpha=1, c=np.sort(self.hull_dist)[::-1],
                                     edgecolor='k', zorder=10000, cmap=cmap, norm=colours.LogNorm(0.02, 2))
                cbar = plt.colorbar(scatter, aspect=30, pad=0.02, ticks=[0, 0.02, 0.04, 0.08, 0.16, 0.32, 0.64, 1.28])
                cbar.ax.set_yticklabels([0, 0.02, 0.04, 0.08, 0.16, 0.32, 0.64, 1.28])
                cbar.set_label('Distance from hull (eV)')
            if self.hull_cutoff != 0:
                # if specified hull cutoff, label and colour those below
                c = self.colours[1]
                for ind in range(len(self.structures)):
                    if self.hull_dist[ind] <= self.hull_cutoff or self.hull_cutoff == 0:
                        scatter.append(ax.scatter(self.structures[ind, 0], self.structures[ind, 1],
                                       s=self.scale*40, lw=lw, alpha=0.9, c=c, edgecolor='k',
                                       label=self.info[ind], zorder=300))
                ax.scatter(self.structures[1:-1, 0], self.structures[1:-1, 1], s=self.scale*30, lw=lw,
                           alpha=0.3, c=self.colours[-2],
                           edgecolor='k', zorder=10)
            # tie lines
            for ind in range(len(self.hull_comp)-1):
                ax.plot([self.hull_comp[ind], self.hull_comp[ind+1]],
                        [self.hull_energy[ind], self.hull_energy[ind+1]],
                        c=self.colours[0], lw=2, alpha=1, zorder=1000, label='')
                if self.hull_cutoff > 0:
                    ax.plot([self.hull_comp[ind], self.hull_comp[ind+1]],
                            [self.hull_energy[ind]+self.hull_cutoff,
                             self.hull_energy[ind+1]+self.hull_cutoff],
                            '--', c=self.colours[1], lw=1, alpha=0.5, zorder=1000, label='')
            # data cursor
            if not dis and self.hull_cutoff != 0:
                datacursor(scatter[:], formatter='{label}'.format, draggable=False,
                           bbox=dict(fc='white'),
                           arrowprops=dict(arrowstyle='simple', alpha=1))
            ax.set_ylim(-0.1 if np.min(self.structure_slice[self.hull.vertices, 1]) > 0
                        else np.min(self.structure_slice[self.hull.vertices, 1])-0.15,
                        0.1 if np.max(self.structure_slice[self.hull.vertices, 1]) > 1
                        else np.max(self.structure_slice[self.hull.vertices, 1])+0.1)
        else:
            scatter = []
            print_exc()
            c = self.colours[1]
            lw = self.scale * 0 if self.mpl_new_ver else 1
            for ind in range(len(self.hull_cursor)):
                scatter.append(ax.scatter(self.hull_cursor[ind]['concentration'], self.hull_cursor[ind]['formation_enthalpy_per_atom'],
                               s=self.scale*40, lw=1.5, alpha=1, c=c, edgecolor='k',
                               zorder=1000))
                ax.plot([0, 1], [0, 0], lw=2, c=self.colours[0], zorder=900)
            for ind in range(len(self.structures)):
                scatter.append(ax.scatter(self.structures[ind, 0], self.structures[ind, 1],
                               s=self.scale*40, lw=lw, alpha=0.9, c=c, edgecolor='k',
                               zorder=300))


        if len(one_minus_x_elem) == 1:
            ax.set_title(x_elem[0] + '$_\mathrm{x}$' + one_minus_x_elem[0] + '$_\mathrm{1-x}$')
        else:
            ax.set_title(x_elem[0] + '$_\mathrm{x}$(' + ''.join([elem for elem in one_minus_x_elem]) + ')$_\mathrm{1-x}$')
        plt.locator_params(nbins=3)
        ax.set_xlabel('$\mathrm{x}$')
        ax.grid(False)
        ax.set_xlim(-0.05, 1.05)
        ax.set_xticks([0, 0.33, 0.5, 0.66, 1])
        ax.set_xticklabels(ax.get_xticks())
        ax.set_ylabel('E$_\mathrm{F}$ (eV/atom)')
        if self.args.get('pdf'):
            plt.savefig(self.elements[0]+self.elements[1]+'_hull.pdf',
                        dpi=400, bbox_inches='tight')
        elif self.args.get('svg'):
            plt.savefig(self.elements[0]+self.elements[1]+'_hull.svg',
                        dpi=200, bbox_inches='tight')
        elif self.args.get('png'):
            plt.savefig(self.elements[0]+self.elements[1]+'_hull.png',
                        dpi=200, bbox_inches='tight')
        else:
            plt.show()

    def plot_2d_hull_bokeh(self):
        """ Plot interactive hull with Bokeh. """
        from bokeh.plotting import figure, save, output_file
        from bokeh.models import ColumnDataSource, HoverTool, Range1d

        # grab tie-line structures
        tie_line_data = dict()
        tie_line_data['composition'] = list()
        tie_line_data['energy'] = list()
        for ind in range(len(self.hull.vertices)):
            if self.structure_slice[self.hull.vertices[ind], 1] <= 0:
                tie_line_data['composition'].append(self.structure_slice[self.hull.vertices[ind], 0])
                tie_line_data['energy'].append(self.structure_slice[self.hull.vertices[ind], 1])
        tie_line_data['energy'] = np.asarray(tie_line_data['energy'])
        tie_line_data['composition'] = np.asarray(tie_line_data['composition'])
        tie_line_data['energy'] = tie_line_data['energy'][np.argsort(tie_line_data['composition'])]
        tie_line_data['composition'] = np.sort(tie_line_data['composition'])

        # points for off hull structures
        hull_data = dict()
        hull_data['composition'] = self.structures[:, 0]
        hull_data['energy'] = self.structures[:, 1]
        hull_data['hull_distance'] = self.hull_dist
        hull_data['formula'], hull_data['text_id'] = [], []
        hull_data['space_group'], hull_data['hull_dist_string'] = [], []
        for structure in self.info:
            hull_data['formula'].append(structure[0])
            hull_data['text_id'].append(structure[1])
            hull_data['space_group'].append(structure[2])
            hull_data['hull_dist_string'].append(structure[3])
        cmap_limits = [0, 0.5]
        colormap = plt.cm.get_cmap('Dark2')
        cmap_input = np.interp(hull_data['hull_distance'], cmap_limits, [0.15, 0.4], left=0.15, right=0.4)
        colours = colormap(cmap_input, 1, True)
        bokeh_colours = ["#%02x%02x%02x" % (r, g, b) for r, g, b in colours[:, 0:3]]
        fixed_colours = colormap([0.0, 0.15], 1, True)
        tie_line_colour, on_hull_colour = ["#%02x%02x%02x" % (r, g, b) for r, g, b in fixed_colours[:, 0:3]]

        tie_line_source = ColumnDataSource(data=tie_line_data)
        hull_source = ColumnDataSource(data=hull_data)

        hover = HoverTool(tooltips="""
                          <div>
                              <div>
                                  <span style="font-size: 12px;">
                                      Formula: @formula <br>
                                      ID: @text_id <br>
                                      Space group: @space_group <br>
                                      Distance from hull: @hull_dist_string
                                  </span>
                              </div>
                          </div>
                          """)

        tools = ['pan', 'wheel_zoom', 'reset', 'save']
        tools.append(hover)
        title = self.elements[0] + 'x' + ''.join(elem for elem in self.elements[1]) + '(1-x)'
        fig = figure(tools=tools, title=title)

        fig.xaxis.axis_label = 'x'
        fig.yaxis.axis_label = 'Formation energy (eV/atom)'
        fig.xaxis.axis_label_text_font_size = '20pt'
        fig.yaxis.axis_label_text_font_size = '20pt'
        fig.yaxis.axis_label_text_font_style = 'normal'
        fig.xaxis.axis_label_text_font_style = 'normal'
        fig.title.text_font_size = '20pt'
        fig.title.align = 'center'

        ylim = [-0.1 if np.min(self.structure_slice[self.hull.vertices, 1]) > 0
                    else np.min(self.structure_slice[self.hull.vertices, 1])-0.15,
                    0.1 if np.max(self.structure_slice[self.hull.vertices, 1]) > 1
                    else np.max(self.structure_slice[self.hull.vertices, 1])+0.1]
        fig.set(x_range=Range1d(-0.1, 1.1), y_range=Range1d(ylim[0], ylim[1]))

        fig.line('composition', 'energy',
                 source=tie_line_source,
                 line_width=4,
                 line_color=tie_line_colour)
        hull_scatter = fig.scatter('composition', 'energy',
                                   source=hull_source,
                                   alpha=1,
                                   size=10,
                                   fill_color=bokeh_colours,
                                   line_color=None)
        fig.tools[0].renderers.append(hull_scatter)
        fig.square('composition', 'energy',
                   source=tie_line_source,
                   line_color='black',
                   color=on_hull_colour,
                   line_width=2,
                   alpha=1,
                   size=10)
        fig.plot_width = 800
        fig.plot_height = 600
        path = '/u/fs1/me388/data/hulls/'
        fname = generate_relevant_path(self.args) + '_' + generate_hash() + '.html'
        output_file(path+fname, title='Convex hull')
        print('Hull will be available shortly at http://www.tcm.phy.cam.ac.uk/~me388/hulls/' + fname)
        save(fig)
        html_string, js_string = get_glmol_placeholder_string()
        with open(path+fname) as f:
            flines = f.readlines()
            for ind, line in enumerate(flines):
                if  "<div class=\"bk-root\">" in line:
                    flines.insert(ind - 1, html_string)
                    break
            flines.append(js_string)
        with open(path+fname, 'w') as f:
            f.write('\n'.join(map(str, flines)))

    def plot_3d_ternary_hull(self):
        """ Plot calculated ternary hull in 3D. """
        fig = plt.figure()
        ax = fig.add_subplot(111, projection='3d')
        coords = self.structures2coords()
        stable = coords[np.where(self.hull_dist < 0 + 1e-9)]
        # stable = [coords[ind] for ind in self.hull.vertices[:-1]]
        stable = np.asarray(stable)
        ax.plot_trisurf(stable[:, 0], stable[:, 1], stable[:, 2], cmap=plt.cm.gnuplot, linewidth=1, color='grey', alpha=0.2)
        ax.scatter(stable[:, 0], stable[:, 1], stable[:, 2], s=100, c='k', marker='o')
        ax.set_zlim(-0.5, 0)
        plt.show()

    def structures2coords(self):
        """ Convert ternary (x, y) in A_x B_y C_{1-x-y}
        to positions projected onto 2D plane. """
        concs = self.structures[:, :-1]
        cos30 = np.cos(np.pi/6)
        cos60 = np.cos(np.pi/3)
        coords = np.zeros_like(self.structures)
        coords[:, 0] = concs[:, 0] + concs[:, 1] * cos60
        coords[:, 1] = concs[:, 1] * cos30
        coords[:, 2] = self.structures[:, -1]
        return coords

    def plot_ternary_hull(self):
        """ Plot calculated ternary hull as a 2D projection. """
        print('Plotting ternary hull...')
        scale = 1
        fontsize=18
        fig, ax = ternary.figure(scale=scale)

        ax.boundary(linewidth=2.0)
        ax.gridlines(color='black', multiple=0.1, linewidth=0.5)


        ax.ticks(axis='lbr', linewidth=1, multiple=0.1)
        ax.clear_matplotlib_ticks()

        ax.annotate(self.elements[0], [1, 0], fontsize=fontsize, zorder=10000)
        ax.annotate(self.elements[1], [0, 0], fontsize=fontsize, zorder=10000)
        ax.annotate(self.elements[2], [1, 1], fontsize=fontsize, zorder=10000)

        concs = np.zeros((len(self.structures), 3))

        concs[:, :-1] = self.structures[:, :-1]
        for i in range(len(concs)):
            concs[i, -1] = 1 - concs[i, 0] - concs[i, 1]

        stable = [concs[ind] for ind in self.hull.vertices]

        ax.scatter(concs, marker='o', color='green', zorder=1000)
        ax.scatter(stable, marker='D', color='red', zorder=10000, s=40, lw=1)
        ax.show()

    def plot_voltage_curve(self):
        """ Plot calculated voltage curve. """
        if self.args.get('pdf') or self.args.get('png'):
            fig = plt.figure(facecolor=None, figsize=(3, 2.7))
        else:
            fig = plt.figure(facecolor=None)
        axQ = fig.add_subplot(111)
        # axQ = ax.twiny()
        if self.args.get('expt') is not None:
            try:
                expt_data = np.loadtxt(self.args.get('expt'), delimiter=',')
                axQ.plot(expt_data[:, 0], expt_data[:, 1], c='k', ls='--')
            except:
                print_exc()
                pass
        print(zip(self.Q, self.voltages))
        for i in range(len(self.voltages)-1):
            axQ.plot([self.Q[i-1], self.Q[i]], [self.voltages[i], self.voltages[i]],
                     lw=2, c=self.colours[0])
            axQ.plot([self.Q[i], self.Q[i]], [self.voltages[i], self.voltages[i+1]],
                     lw=2, c=self.colours[0])
        for i in range(len(self.x)):
            if self.x[i] < 1e9: 
                string_stoich = ''
                if abs(np.ceil(self.x[i])-self.x[i]) > 1e-8:
                    string_stoich = str(round(self.x[i], 1))
                else:
                    string_stoich = str(int(np.ceil(self.x[i])))
                if string_stoich is '1':
                    string_stoich = ''
                if string_stoich is '0':
                    string_stoich = ''
                else:
                    string_stoich = self.elements[0] + '$_{' + string_stoich + '}$' + self.elements[1]
                axQ.annotate(string_stoich,
                             xy=(self.Q[i], self.voltages[i]+0.001),
                             textcoords='data',
                             ha='center',
                             zorder=9999)
        axQ.set_ylabel('Voltage (V)')
        axQ.set_xlabel('Gravimetric cap. (mAh/g)')
        start, end = axQ.get_ylim()
        axQ.set_ylim(start-0.01, end+0.01)
        axQ.grid('off')
        plt.tight_layout(pad=0.0, h_pad=1.0, w_pad=0.2)
        if self.args.get('pdf'):
            plt.savefig(self.elements[0]+self.elements[1]+'_voltage.pdf',
                        dpi=300)
        elif self.args.get('png'):
            plt.savefig(self.elements[0]+self.elements[1]+'_voltage.png',
                        dpi=300, bbox_inches='tight')
        else:
            plt.show()

    def plot_volume_curve(self):
        """ Plot calculate volume curve. """
        if self.args.get('pdf') or self.args.get('png'):
            fig = plt.figure(facecolor=None, figsize=(2.7, 2.7))
        else:
            fig = plt.figure(facecolor=None)
        ax = fig.add_subplot(111)
        stable_hull_dist = get_array_from_cursor(self.hull_cursor, 'hull_distance')
        hull_vols = []
        hull_comps = []
        bulk_vol = self.vol_per_y[-1]
        for i in range(len(self.vol_per_y)):
            if stable_hull_dist[i] <= 0 + 1e-16:
                hull_vols.append(self.vol_per_y[i])
                hull_comps.append(self.x[i])
                s = 40
                zorder = 1000
                alpha = 1
                markeredgewidth = 1.5
                c = self.colours[1]
            else:
                s = 30
                zorder = 900
                markeredgewidth = 0.5
                alpha = 0.8
                c = 'grey'
            ax.scatter(self.x[i], self.vol_per_y[i]/bulk_vol, marker='o', s=s, edgecolor='k', lw=markeredgewidth,
                       c=c, zorder=zorder)
        hull_comps, hull_vols = np.asarray(hull_comps), np.asarray(hull_vols)
        ax.plot(hull_comps, hull_vols/bulk_vol, marker='o', lw=4,
                c=self.colours[0], zorder=100)
        ax.set_xlabel('$\mathrm{u}$ in $\mathrm{'+self.elements[0]+'_u'+self.elements[1]+'}$')
        ax.set_ylabel('Volume ratio with bulk')
        start, end = ax.get_xlim()
        ax.xaxis.set_ticks(range(0, int(end)+1, 1))
        start, end = ax.get_ylim()
        ax.yaxis.set_ticks(range(1, int(end)+1, 1))
        ax.yaxis.tick_right()
        ax.yaxis.set_label_position('right')
        ax.set_xticklabels(ax.get_xticks())
        ax.grid('off')
        plt.tight_layout(pad=0.0, h_pad=1.0, w_pad=0.2)
        if self.args.get('pdf'):
            plt.savefig(self.elements[0]+self.elements[1]+'_volume.pdf',
                        dpi=300)
        elif self.args.get('png'):
            plt.savefig(self.elements[0]+self.elements[1]+'_volume.png',
                        dpi=300, bbox_inches='tight')
        else:
            plt.show()

    def subplot_voltage_hull(self, dis=False):
        """ Plot calculated hull with inset voltage curve. """
        if self.args.get('pdf') or self.args.get('png'):
            fig = plt.figure(facecolor=None, figsize=(4.5, 1.5))
        else:
            fig = plt.figure(facecolor=None, figsize=(4.5, 1.5))
        ax = plt.subplot2grid((1, 3), (0, 0), colspan=2)
        ax2 = plt.subplot2grid((1, 3), (0, 2))
        scatter = []
        hull_scatter = []
        x_elem = self.elements[0]
        one_minus_x_elem = self.elements[1]
        plt.locator_params(nbins=3)
        # star structures on hull
        for ind in range(len(self.hull.vertices)):
            if self.structure_slice[self.hull.vertices[ind], 1] <= 0:
                hull_scatter.append(ax.scatter(self.structure_slice[self.hull.vertices[ind], 0],
                                               self.structure_slice[self.hull.vertices[ind], 1],
                                               c=self.colours[0],
                                               marker='*', zorder=99999, edgecolor='k',
                                               s=self.scale*150, lw=1, alpha=1,
                                               label=self.info[self.hull.vertices[ind]]))
        lw = self.scale * 0.05 if self.mpl_new_ver else 1
        # points for off hull structures
        for ind in range(len(self.structures)):
            if self.hull_dist[ind] <= self.hull_cutoff or self.hull_cutoff == 0:
                c = self.colours[self.source_ind[ind]] \
                    if self.hull_cutoff == 0 else self.colours[1]
                scatter.append(ax.scatter(self.structures[ind, 0], self.structures[ind, 1],
                               s=self.scale*30, lw=lw, alpha=0.9, c=c, edgecolor='k',
                               label=self.info[ind], zorder=100))
        if self.hull_cutoff != 0:
            c = self.colours[self.source_ind[ind]] if self.hull_cutoff == 0 else self.colours[1]
            ax.scatter(self.structures[1:-1, 0], self.structures[1:-1, 1], s=self.scale*30, lw=lw,
                       alpha=0.3, c=self.colours[-2],
                       edgecolor='k', zorder=10)
        # tie lines
        for ind in range(len(self.hull_comp)-1):
            ax.plot([self.hull_comp[ind], self.hull_comp[ind+1]],
                    [self.hull_energy[ind], self.hull_energy[ind+1]],
                    c=self.colours[0], lw=2, alpha=1, zorder=1000, label='')
            if self.hull_cutoff > 0:
                ax.plot([self.hull_comp[ind], self.hull_comp[ind+1]],
                        [self.hull_energy[ind]+self.hull_cutoff,
                         self.hull_energy[ind+1]+self.hull_cutoff],
                        '--', c=self.colours[1], lw=1, alpha=0.5, zorder=1000, label='')
        ax.set_xlim(-0.05, 1.05)
        # data cursor
        if not dis:
            datacursor(scatter[:], formatter='{label}'.format, draggable=False,
                       bbox=dict(fc='white'),
                       arrowprops=dict(arrowstyle='simple', alpha=1))
        ax.set_ylim(-0.1 if np.min(self.structure_slice[self.hull.vertices, 1]) > 0
                    else np.min(self.structure_slice[self.hull.vertices, 1]) - 0.05,
                    0.5 if np.max(self.structures[:, 1]) > 0.5
                    else np.max(self.structures[:, 1]) + 0.1)
        ax.set_title('$\mathrm{'+x_elem+'_x'+one_minus_x_elem+'_{1-x}}$')
        ax.set_xlabel('$x$', labelpad=-3)
        ax.set_xticks([0, 1])
        ax.set_yticks([-0.4, 0, 0.4])
        ax.set_ylabel('$E_\mathrm{F}$ (eV/atom)')
        # plot voltage
        for i in range(2, len(self.voltages)):
            ax2.scatter(self.x[i-1], self.voltages[i-1],
                        marker='*', s=100, edgecolor='k', c=self.colours[0], zorder=1000)
            ax2.plot([self.x[i], self.x[i]], [self.voltages[i], self.voltages[i-1]],
                     lw=2, c=self.colours[0])
            ax2.plot([self.x[i-1], self.x[i]], [self.voltages[i-1], self.voltages[i-1]],
                     lw=2, c=self.colours[0])
        ax2.set_ylabel('Voltage (V)')
        ax2.yaxis.set_label_position("right")
        ax2.yaxis.tick_right()
        ax2.set_xlim(0, np.max(np.asarray(self.x[1:]))+1)
        ax2.set_ylim(np.min(np.asarray(self.voltages[1:]))-0.1,
                     np.max(np.asarray(self.voltages[1:]))+0.1)
        ax2.set_xlabel('$n_\mathrm{Li}$', labelpad=-3)
        if self.args.get('pdf'):
            plt.savefig(self.elements[0]+self.elements[1]+'_hull_voltage.pdf',
                        dpi=300, bbox_inches='tight')
        elif self.args.get('png'):
            plt.savefig(self.elements[0]+self.elements[1]+'_hull_voltage.png',
                        dpi=300, bbox_inches='tight')
        else:
            fig.show()

    def set_plot_param(self):
        """ Set some plotting options global to
        voltage and hull plots.
        """
        try:
            plt.style.use('bmh')
        except:
            pass
        if self.args.get('pdf') or self.args.get('png'):
            try:
                plt.style.use('article')
            except:
                pass
        self.scale = 1
        try:
            c = plt.cm.viridis(np.linspace(0, 1, 100))
            del c
            self.mpl_new_ver = True
        except:
            self.mpl_new_ver = False
        from palettable.colorbrewer.qualitative import Dark2_8
        from palettable.colorbrewer.qualitative import Set3_10
        # if len(self.source_list) < 6:
            # self.colours = Dark2_8.hex_colors[1:len(self.source_list)+1]
        # else:
        self.colours = Dark2_8.hex_colors[1:]
        self.colours.extend(Dark2_8.hex_colors[1:])
        # first colour reserved for hull
        self.colours.insert(0, Dark2_8.hex_colors[0])
        # penultimate colour reserved for off hull above cutoff
        self.colours.append(Dark2_8.hex_colors[-1])
        # last colour reserved for OQMD
        self.colours.append(Set3_10.hex_colors[-1])
        return

    def metastable_voltage_profile(self):
        """ Construct a smeared voltage profile from metastable hull,
        weighting either with Boltzmann, PDF overlap of nothing.
        """
        print('Generating metastable voltage profile...')
        structures = self.hull_cursor[:-1]
        guest_atoms = []
        for i in range(len(structures)):
            stoich = self.get_formation_energy(structures[i])
            try:
                structures['num_a'] = stoich / (1 - stoich)
            except:
                structures['num_a'] = float('inf')
        for i in range(len(structures)):
            guest_atoms.append(structures[i]['num_a'])
            structures[i]['capacity'] = get_capacities(guest_atoms[-1], get_molar_mass(self.elements[1]))
        # guest_atoms = np.asarray(guest_atoms)
        # max_guest = np.max(guest_atoms)
        # grab reference cathode
        reference_cathode = self.hull_cursor[-1]

        # set up running average voltage profiles
        num_divisions = 100
        running_average_profile = np.zeros((num_divisions))
        advanced_average_profile = np.zeros_like(running_average_profile)
        diff_average_profile = np.ones_like(running_average_profile)
        # replace with max cap
        capacity_space = np.linspace(0, 2000, num_divisions)
        all_voltage_profiles = []
        # set convergance of voltage profile tolerance
        tolerance = 1e-9 * num_divisions

        def boltzmann(structures):
            idx = np.random.randint(0, len(structures))
            return structures[idx]

        def pdf_overlap(structures):
            idx = np.random.randint(0, len(structures))
            return structures[idx]

        def pick_metastable_structure(structures, weighting=None, last=None):
            """ Pick an acceptable metastable structure. """
            count = 0
            while True:
                count += 1
                if count > 1000:
                    exit('Something went wrong...')
                test = structures[np.random.randint(0, len(structures))]
                if test['num_a'] < last['num_a']:
                    print(count)
                    return test
            else:
                return weighting(structures)

        def get_voltage_profile_segment(structure_new, structure_old):
            """ Return voltage between two structures. """
            V = (-(structure_new['enthalpy_per_b'] - structure_old['enthalpy_per_b']) /
                 (structure_new['num_a'] - structure_old['num_a']) +
                 (self.mu_enthalpy[0]))
            if structure_old['num_a'] == float('inf'):
                V = 0
            return V

        def interp_steps(xspace, x, y):
            """ Interpolate (x,y) across xspace with step functions. """
            yspace = np.zeros_like(xspace)
            for x_val, y_val in zip(x, y):
                yspace[np.where(xspace <= x_val)] = y_val
            return yspace

        weighting = None
        converged = False
        convergence_window = 3
        last_converged = False
        num_contribs = 0
        num_converged = 0
        num_trials = 100000
        while not converged:
            if np.abs(diff_average_profile).sum() < tolerance:
                if num_converged > convergence_window:
                    converged = True
                    break
                if not last_converged:
                    last_converged = True
                    num_converged = 1
                if last_converged:
                    num_converged += 1
            if num_contribs > num_trials:
                break
            # print('Sampling path', num_contribs)
            delithiated = False
            voltage_profile = []
            prev = reference_cathode
            path_structures = list(structures)
            while not delithiated:
                next = pick_metastable_structure(path_structures, weighting=weighting, last=prev)
                idx = path_structures.index(next)
                path_structures = path_structures[:idx]
                if prev['num_a'] != float('inf'):
                    voltage_profile.append([next['capacity'], get_voltage_profile_segment(next, prev)])
                if next['num_a'] == 0:
                    delithiated = True
                else:
                    prev = next
            if delithiated and len(voltage_profile) != 0:
                # piecewise linear interpolation of V and add to running average
                voltage_profile = np.asarray(voltage_profile)
                # print(voltage_profile)
                advanced_average_profile += interp_steps(capacity_space, voltage_profile[:, 0], voltage_profile[:, 1])
                num_contribs += 1
                diff_average_profile = advanced_average_profile/num_contribs - running_average_profile
                # print(advanced_average_profile)
                all_voltage_profiles.append(voltage_profile)
                running_average_profile = advanced_average_profile/num_contribs

        print('Convergence achieved with', num_contribs, 'paths.')
        print(np.abs(diff_average_profile).sum(), tolerance)
        fig = plt.figure()
        ax = fig.add_subplot(111)
        # for idx, vp in enumerate(all_voltage_profiles):
            # if idx % len(all_voltage_profiles) == 0:
                # ax.scatter(vp[:, 0], vp[:, 1], s=50)
            # print(vp)
        for i in range(2, len(self.voltages)):
            ax.plot([self.Q[i], self.Q[i]], [self.voltages[i], self.voltages[i-1]],
                    lw=2, c=self.colours[0])
            ax.plot([self.Q[i-1], self.Q[i]], [self.voltages[i-1], self.voltages[i-1]],
                    lw=2, c=self.colours[0])
        ax.scatter(capacity_space, running_average_profile, c='r', marker='*', s=50)
        plt.show()

class FakeHull:
    """ Implements a thin class to mimic a ConvexHull object
    that would otherwise be undefined for two points. """
    def __init__(self):
        """ Define the used hull properties. """
        self.vertices = [0, 1]
