# coding: utf-8
""" This file implements some scraper functions for
Quantum Espresso-related inputs and outputs.
"""

from __future__ import print_function
# matador modules
from matador.utils.cell_utils import cart2abc, cart2volume
from matador.utils.chem_utils import RY_TO_EV, KBAR_TO_GPA
# external libraries
try:
    import bson.json_util as json
except:
    pass
# standard library
from collections import defaultdict
from os import stat
from math import gcd
from pwd import getpwuid
from traceback import print_exc


def pwout2dict(seed, db=True, **kwargs):
    """ Extract available information from pw.x .out file. """
    pwout = defaultdict(list)
    try:
        # read .pwout file into array
        ext = '.out'
        if seed.endswith('.out'):
            seed = seed.replace('.out', '')
        if seed.endswith('.in'):
            ext = '.in'
            seed = seed.replace('.in', '')
        with open(seed+ext, 'r') as f:
            flines = f.readlines()
        # add .pwout to source
        pwout['source'].append(seed+'.pwout')
        # grab file owner username
        try:
            pwout['user'] = getpwuid(stat(seed+'.pwout').st_uid).pw_name
        except:
            if kwargs.get('debug'):
                print(seed+'.pwout has no owner.')
            pwout['user'] == 'xxx'
        if 'CollCode' in seed:
            pwout['icsd'] = seed.split('CollCode')[-1]
        for ind, line in enumerate(reversed(flines)):
            ind = len(flines) - 1 - ind
            if 'cell_parameters (angstrom)' in line.lower() and 'lattice_cart' not in pwout:
                pwout['lattice_cart'] = []
                for j in range(3):
                    line = flines[ind+j+1].strip().split()
                    pwout['lattice_cart'].append(list(map(float, line)))
                pwout['cell_volume'] = cart2volume(pwout['lattice_cart'])
            elif 'atomic_positions' in line.lower() and 'positions_frac' not in pwout:
                pwout['positions_frac'] = []
                pwout['atom_types'] = []
                j = 1
                if ext is '.out':
                    while 'End final coordinates' not in flines[j+ind]:
                        line = flines[j+ind].strip().split()
                        pwout['atom_types'].append(line[0])
                        pwout['positions_frac'].append(list(map(float, line[1:5])))
                        j += 1
                else:
                    while True:
                        try:
                            line = flines[j+ind].strip().split()
                            pwout['atom_types'].append(line[0])
                            pwout['positions_frac'].append(list(map(float, line[1:5])))
                            j += 1
                        except:
                            break
                pwout['num_atoms'] = len(pwout['atom_types'])
            elif 'final enthalpy' in line.lower() and 'enthalpy' not in pwout:
                pwout['enthalpy'] = RY_TO_EV * float(line.lower().split()[-2])
            elif 'total   stress' in line.lower() and 'pressure' not in pwout:
                pwout['pressure'] = KBAR_TO_GPA * float(line.lower().split()[-1])
            elif all(key in pwout for key in ['enthalpy', 'pressure', 'lattice_cart', 'positions_frac']):
                break
        # get abc lattice
        pwout['lattice_abc'] = cart2abc(pwout['lattice_cart'])
        # calculate stoichiometry
        pwout['stoichiometry'] = defaultdict(float)
        for atom in pwout['atom_types']:
            if atom not in pwout['stoichiometry']:
                pwout['stoichiometry'][atom] = 0
            pwout['stoichiometry'][atom] += 1
        gcd_val = 0
        for atom in pwout['atom_types']:
            if gcd_val == 0:
                gcd_val = pwout['stoichiometry'][atom]
            else:
                gcd_val = gcd(pwout['stoichiometry'][atom], gcd_val)
        # convert stoichiometry to tuple for fryan
        temp_stoich = []
        for key, value in pwout['stoichiometry'].items():
            if float(value)/gcd_val % 1 != 0:
                temp_stoich.append([key, float(value)/gcd_val])
            else:
                temp_stoich.append([key, value/gcd_val])
        pwout['stoichiometry'] = temp_stoich
        atoms_per_fu = 0
        for elem in pwout['stoichiometry']:
            atoms_per_fu += elem[1]
        pwout['num_fu'] = len(pwout['atom_types']) / atoms_per_fu
    except Exception as oops:
        if kwargs.get('verbosity') is not None:
            if kwargs.get('verbosity') > 0:
                print_exc()
                print('Error in .pwout file', seed + '.pwout, skipping...')
        if type(oops) == IOError:
            print_exc()
        return seed+'.pwout\t\t' + str(type(oops)) + ' ' + str(oops) + '\n', False
    if kwargs.get('verbosity') is not None:
        if kwargs.get('verbosity') > 4:
            print(json.dumps(pwout, indent=2))
    return pwout, True
