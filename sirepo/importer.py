"""
This script is to parse SRW Python scripts and to produce JSON-file with the parsed data.
It's highly dependent on the external Sirepo/SRW libraries and is written to allow parsing of the .py files using
SRW objects.
"""
from __future__ import absolute_import, division, print_function

import ast
import inspect
import json
import re
import traceback

import py
import requests
from pykern import pkio
from pykern import pkrunpy
from pykern.pkdebug import pkdp
from srwl_bl import srwl_uti_parse_options
from srwl_bl import srwl_uti_std_options

try:
    import cPickle as pickle
except:
    import pickle


def import_python(code, tmp_dir, lib_dir, user_filename=None, arguments=None):
    """Converts script_text into json and stores as new simulation.

    Avoids too much data back to the user in the event of an error.
    This could be a potential security issue, because the script
    could be used to probe the system.

    Args:
        simulation_type (str): always "srw", but used to find lib dir
        code (str): Python code that runs SRW
        user_filename (str): uploaded file name for log

    Returns:
        error: string containing error or None
        dict: simulation data
    """
    error = 'Import failed: error unknown'
    script = None
    try:
        with pkio.save_chdir(tmp_dir):
            # This string won't show up anywhere
            script = pkio.write_text('in.py', code)
            o = SRWParser(
                script,
                lib_dir=py.path.local(lib_dir),
                user_filename=user_filename,
                arguments=arguments,
            )
            return None, o.data
    except Exception as e:
        lineno = _find_line_in_trace(script) if script else None
        # Avoid
        pkdp(
            'Error: {}; exception={}; script={}; filename={}; stack:\n{}',
            error,
            e,
            script,
            user_filename,
            traceback.format_exc(),
        )
        error = 'Error on line {}: {}'.format(lineno or '?', str(e)[:50])
    return error, None


def get_json(json_url):
    return json.loads(requests.get(json_url).text)


static_url = 'https://raw.githubusercontent.com/radiasoft/sirepo/master/sirepo/package_data/static'
static_js_url = static_url + '/js'
static_json_url = static_url + '/json'


def list2dict(data_list):
    """
    The function converts list of lists to a dictionary with keys from 1st elements and values from 3rd elements.

    :param data_list: list of SRW parameters (e.g., 'appParam' in Sirepo's *.py files).
    :return out_dict: dictionary with all parameters.
    """

    out_dict = {}

    for i in range(len(data_list)):
        out_dict[data_list[i][0]] = data_list[i][2]

    return out_dict


class Struct(object):
    def __init__(self, **entries):
        self.__dict__.update(entries)


# For sourceIntensityReport:
try:
    import py.path
    from pykern import pkresource

    static_dir = py.path.local(pkresource.filename('static'))
except:
    static_dir = '/home/vagrant/src/radiasoft/sirepo/sirepo/package_data/static'

static_js_dir = static_dir + '/js'
static_json_dir = static_dir + '/json'


def get_default_drift():
    """The function parses srw.js file to find the default values for drift propagation parameters, which can be
    sometimes missed in the exported .py files (when distance = 0), but should be presented in .json files.

    :return default_drift_prop: found list as a string.
    """

    try:
        file_content = requests.get(static_js_url + '/srw.js').text
    except:
        file_content = u''

    default_drift_prop = u'[0, 0, 1, 1, 0, 1.0, 1.0, 1.0, 1.0]'

    try:  # open(file_name, 'r') as f:
        content = file_content.split('\n')
        for i in range(len(content)):
            if content[i].find('function defaultDriftPropagationParams()') >= 0:
                # Find 'return' statement:
                for j in range(10):
                    '''
                        function defaultDriftPropagationParams() {
                            return [0, 0, 1, 1, 0, 1.0, 1.0, 1.0, 1.0];
                        }
                    '''
                    if content[i + j].find('return') >= 0:
                        default_drift_prop = content[i + j].replace('return ', '').replace(';', '').strip()
                        break
                break
    except:
        pass

    default_drift_prop = ast.literal_eval(default_drift_prop)

    return default_drift_prop


# Mapping all the values to a dictionary:
def beamline_element(obj, idx, title, elem_type, position):
    data = {}

    data['id'] = idx
    data['type'] = unicode(elem_type)
    data['title'] = unicode(title)
    data['position'] = position

    if elem_type == 'aperture':
        data['shape'] = unicode(obj.shape)

        data['horizontalOffset'] = obj.x
        data['verticalOffset'] = obj.y
        data['horizontalSize'] = obj.Dx * 1e3
        data['verticalSize'] = obj.Dy * 1e3

    elif elem_type == 'mirror':
        keys = ['grazingAngle', 'heightAmplification', 'heightProfileFile', 'horizontalTransverseSize',
                'orientation', 'verticalTransverseSize']
        for key in keys:
            if type(obj.input_parms) == tuple:
                data[key] = obj.input_parms[0][key]
            else:
                data[key] = obj.input_parms[key]

        # Should be multiplied by 1000.0:
        for key in ['horizontalTransverseSize', 'verticalTransverseSize']:
            data[key] *= 1000.0

        data['heightProfileFile'] = 'mirror_1d.dat'

    elif elem_type == 'crl':
        keys = ['attenuationLength', 'focalPlane', 'horizontalApertureSize', 'numberOfLenses', 'radius',
                'refractiveIndex', 'shape', 'verticalApertureSize', 'wallThickness']

        for key in keys:
            data[key] = obj.input_parms[key]

        # Should be multiplied by 1000.0:
        for key in ['horizontalApertureSize', 'verticalApertureSize']:
            data[key] *= 1000.0

        '''
        data['attenuationLength'] = None  # u'7.31294e-03'
        if obj.Fx > 1e20 and obj.Fy < 1e20:
            data['focalPlane'] = 2  # 2
        else:
            data['focalPlane'] = 1
        data['horizontalApertureSize'] = None  # u'1'
        data['numberOfLenses'] = None  # u'1'
        data['radius'] = None  # u'1.5e-03'
        data['refractiveIndex'] = None  # u'4.20756805e-06'
        data['shape'] = None  # 1
        data['verticalApertureSize'] = None  # u'2.4'
        data['wallThickness'] = None  # u'80.e-06'
        '''

    elif elem_type == 'lens':
        data['horizontalFocalLength'] = obj.Fx  # u'3.24479',
        data['horizontalOffset'] = obj.x  # 0
        data['verticalFocalLength'] = obj.Fy  # u'1.e+23'
        data['verticalOffset'] = obj.y  # 0

    elif elem_type == 'sphericalMirror':
        '''
                "grazingAngle": 13.9626,
                "heightAmplification": 1,
                "heightProfileFile": null,
                "normalVectorX": 0,
                "normalVectorY": 0.9999025244842406,
                "normalVectorZ": -0.013962146326506367,
                "orientation": "x",
                "radius": 1049,
                "sagittalSize": 0.11,
                "tangentialSize": 0.3,
                "tangentialVectorX": 0,
                "tangentialVectorY": 0.013962146326506367,
        '''
        # Fixed values in srw.js:
        data['grazingAngle'] = 13.9626000172
        data['heightAmplification'] = 1
        data['heightProfileFile'] = None
        data['orientation'] = u'x'

        data['normalVectorX'] = obj.nvx
        data['normalVectorY'] = obj.nvy
        data['normalVectorZ'] = obj.nvz
        data['radius'] = obj.rad
        data['sagittalSize'] = obj.ds
        data['tangentialSize'] = obj.dt
        data['tangentialVectorX'] = obj.tvx
        data['tangentialVectorY'] = obj.tvy

    elif elem_type == 'grating':
        '''
                "diffractionOrder": -1,
                "grazingAngle": 25.1327,
                "grooveDensity0": 100,
                "grooveDensity1": 0.02666,
                "grooveDensity2": 7.556e-09,
                "grooveDensity3": -1.89085e-09,
                "grooveDensity4": -5.04636e-13,
                "normalVectorX": 0,
                "normalVectorY": -0.9996841903193807,
                "normalVectorZ": -0.025130054227639583,
                "sagittalSize": 0.05,
                "tangentialSize": 0.22,
                "tangentialVectorX": 0,
                "tangentialVectorY": -0.025130054227639583,
        '''
        # Fixed values in srw.js:
        data['grazingAngle'] = 12.9555790185373

        data['diffractionOrder'] = obj.m
        data['grooveDensity0'] = obj.grDen
        data['grooveDensity1'] = obj.grDen1
        data['grooveDensity2'] = obj.grDen2
        data['grooveDensity3'] = obj.grDen3
        data['grooveDensity4'] = obj.grDen4
        data['normalVectorX'] = obj.mirSub.nvx
        data['normalVectorY'] = obj.mirSub.nvy
        data['normalVectorZ'] = obj.mirSub.nvz
        data['sagittalSize'] = obj.mirSub.ds
        data['tangentialSize'] = obj.mirSub.dt
        data['tangentialVectorX'] = obj.mirSub.tvx
        data['tangentialVectorY'] = obj.mirSub.tvy

    elif elem_type == 'ellipsoidMirror':
        '''
                "firstFocusLength": 137.4,
                "focalLength": 2,
                "grazingAngle": 13.9626,
                "heightAmplification": 1,
                "heightProfileFile": null,
                "normalVectorX": -0.9999025244842406,
                "normalVectorY": 0,
                "normalVectorZ": -0.013962146326506367,
                "orientation": "x",
                "sagittalSize": 0.025,
                "tangentialSize": 0.4,
                "tangentialVectorX": -0.013962146326506367,
                "tangentialVectorY": 0,
        '''
        # Fixed values in srw.js:
        data['heightAmplification'] = 1
        data['heightProfileFile'] = None
        data['orientation'] = u'x'

        data['firstFocusLength'] = obj.p
        data['focalLength'] = obj.q
        data['grazingAngle'] = obj.angGraz * 1e3
        data['normalVectorX'] = obj.nvx
        data['normalVectorY'] = obj.nvy
        data['normalVectorZ'] = obj.nvz
        data['sagittalSize'] = obj.ds
        data['tangentialSize'] = obj.dt
        data['tangentialVectorX'] = obj.tvx
        data['tangentialVectorY'] = obj.tvy

    elif elem_type == 'watch':
        pass

    else:
        raise Exception('Element type <{}> does not exist.'.format(elem_type))

    return data


def get_beamline(obj_arOpt, init_distance=20.0):
    """The function creates a beamline from the provided object and/or AST tree.

    :param obj_arOpt: SRW object containing properties of the beamline elements.
    :param init_distance: distance from the source to the first element (20.0 m by default).
    :return elements_list: list of all found beamline elements.
    """

    num_elements = len(obj_arOpt)

    elements_list = []

    # The dictionary to count the elements of different types:
    names = {
        'S': 0,
        'O': 0,
        'HDM': 0,
        'CRL': 0,
        'KL': 0,
        'KLA': 0,
        'AUX': 0,
        'M': 0,  # mirror
        'G': 0,  # grating
        'Sample': '',
    }

    positions = []  # a list of dictionaries with sequence of distances between elements
    # positions_from_source = []  # a list with sequence of distances from source

    d_src = init_distance
    counter = 0
    for i in range(num_elements):
        name = obj_arOpt[i].__class__.__name__
        try:
            next_name = obj_arOpt[i + 1].__class__.__name__
        except:
            next_name = None

        if name == 'SRWLOptD':
            d = obj_arOpt[i].L
        else:
            d = 0.0
        d_src += d

        if (len(positions) == 0) or \
                (name != 'SRWLOptD') or \
                (name == 'SRWLOptD' and next_name == 'SRWLOptD') or \
                (name == 'SRWLOptD' and (i + 1) == num_elements):

            counter += 1

            elem_type = ''

            if name == 'SRWLOptA':
                if obj_arOpt[i].ap_or_ob == 'a':
                    elem_type = 'aperture'
                    key = 'S'
                else:
                    elem_type = 'obstacle'
                    key = 'O'

            elif name == 'SRWLOptT':
                # Check the type based on focal lengths of the element:
                if type(obj_arOpt[i].input_parms) == tuple:
                    elem_type = obj_arOpt[i].input_parms[0]['type']
                else:
                    elem_type = obj_arOpt[i].input_parms['type']

                if elem_type == 'mirror':  # mirror, no surface curvature
                    key = 'HDM'

                elif elem_type == 'crl':  # CRL
                    key = 'CRL'

            elif name == 'SRWLOptL':
                key = 'KL'
                elem_type = 'lens'

            elif name == 'SRWLOptMirSph':
                key = 'M'
                elem_type = 'sphericalMirror'

            elif name == 'SRWLOptG':
                key = 'G'
                elem_type = 'grating'

            elif name == 'SRWLOptMirEl':
                key = 'M'
                elem_type = 'ellipsoidMirror'

            elif name == 'SRWLOptD':
                key = 'AUX'
                elem_type = 'watch'

            # Last element is Sample:
            if (name == 'SRWLOptD' and (i + 1) == num_elements):
                key = 'Sample'
                elem_type = 'watch'

            try:
                names[key] += 1
            except:
                pass

            title = key + str(names[key])

            positions.append({
                'id': counter,
                'object': obj_arOpt[i],
                'elem_class': name,
                'elem_type': elem_type,
                'title': title,
                'dist': d,
                'dist_source': d_src,
            })

    for i in range(len(positions)):
        data = beamline_element(
            positions[i]['object'],
            positions[i]['id'],
            positions[i]['title'],
            positions[i]['elem_type'],
            positions[i]['dist_source']
        )
        elements_list.append(data)

    return elements_list


def get_propagation(op):
    prop_dict = {}
    counter = 0
    for i in range(len(op.arProp) - 1):
        name = op.arOpt[i].__class__.__name__
        try:
            next_name = op.arOpt[i + 1].__class__.__name__
        except:
            next_name = None

        if (name != 'SRWLOptD') or \
                (name == 'SRWLOptD' and next_name == 'SRWLOptD') or \
                ((i + 1) == len(op.arProp) - 1):  # exclude last drift
            counter += 1
            prop_dict[unicode(str(counter))] = [op.arProp[i]]
            if next_name == 'SRWLOptD':
                prop_dict[unicode(str(counter))].append(op.arProp[i + 1])
            else:
                prop_dict[unicode(str(counter))].append(get_default_drift())

    return prop_dict


def parsed_dict(v, op):
    std_options = Struct(**list2dict(srwl_uti_std_options()))

    beamlines_list = get_beamline(op.arOpt, v.op_r)

    def _default_value(parm, obj, std, def_val=None):
        if not hasattr(obj, parm):
            try:
                return getattr(std, parm)
            except:
                if def_val is not None:
                    return def_val
                else:
                    return ''
        try:
            return getattr(obj, parm)
        except:
            if def_val is not None:
                return def_val
            else:
                return ''

    # This dictionary will is used for both initial intensity report and for watch point:
    initialIntensityReport = {
        u'characteristic': v.si_type,
        u'fieldUnits': 2,
        u'polarization': v.si_pol,
        u'precision': v.w_prec,
        u'sampleFactor': 0,
    }

    # Default electron beam:
    if hasattr(v, 'ebm_nm'):
        source_type = u'u'

        electronBeam = {
            u'beamSelector': unicode(v.ebm_nm),
            u'current': v.ebm_i,
            u'energy': _default_value('ueb_e', v, std_options, 3.0),
            u'energyDeviation': _default_value('ebm_de', v, std_options, 0.0),
            u'horizontalAlpha': _default_value('ueb_alpha_x', v, std_options, 0.0),
            u'horizontalBeta': _default_value('ueb_beta_x', v, std_options, 2.02),
            u'horizontalDispersion': _default_value('ueb_eta_x', v, std_options, 0.0),
            u'horizontalDispersionDerivative': _default_value('ueb_eta_x_pr', v, std_options, 0.0),
            u'horizontalEmittance': _default_value('ueb_emit_x', v, std_options, 9e-10) * 1e9,
            u'horizontalPosition': v.ebm_x,
            u'isReadOnly': False,
            u'name': unicode(v.ebm_nm),
            u'rmsSpread': _default_value('ueb_sig_e', v, std_options, 0.00089),
            u'verticalAlpha': _default_value('ueb_alpha_y', v, std_options, 0.0),
            u'verticalBeta': _default_value('ueb_beta_y', v, std_options, 1.06),
            u'verticalDispersion': _default_value('ueb_eta_y', v, std_options, 0.0),
            u'verticalDispersionDerivative': _default_value('ueb_eta_y_pr', v, std_options, 0.0),
            u'verticalEmittance': _default_value('ueb_emit_y', v, std_options, 8e-12) * 1e9,
            u'verticalPosition': v.ebm_y,
        }

        undulator = {
            u'horizontalAmplitude': _default_value('und_bx', v, std_options, 0.0),
            u'horizontalInitialPhase': _default_value('und_phx', v, std_options, 0.0),
            u'horizontalSymmetry': v.und_sx,
            u'length': v.und_len,
            u'longitudinalPosition': v.und_zc,
            u'period': v.und_per * 1e3,
            u'verticalAmplitude': _default_value('und_by', v, std_options, 0.88770981),
            u'verticalInitialPhase': _default_value('und_phy', v, std_options, 0.0),
            u'verticalSymmetry': v.und_sy,
        }

        gaussianBeam = {
            u'energyPerPulse': None,
            u'polarization': 1,
            u'rmsPulseDuration': None,
            u'rmsSizeX': None,
            u'rmsSizeY': None,
            u'waistAngleX': None,
            u'waistAngleY': None,
            u'waistX': None,
            u'waistY': None,
            u'waistZ': None,
        }

    else:
        source_type = u'g'
        electronBeam = {
            u'beamSelector': None,
            u'current': None,
            u'energy': None,
            u'energyDeviation': None,
            u'horizontalAlpha': None,
            u'horizontalBeta': 1.0,
            u'horizontalDispersion': None,
            u'horizontalDispersionDerivative': None,
            u'horizontalEmittance': None,
            u'horizontalPosition': None,
            u'isReadOnly': False,
            u'name': None,
            u'rmsSpread': None,
            u'verticalAlpha': None,
            u'verticalBeta': 1.0,
            u'verticalDispersion': None,
            u'verticalDispersionDerivative': None,
            u'verticalEmittance': None,
            u'verticalPosition': None,
        }
        undulator = {
            u'horizontalAmplitude': None,
            u'horizontalInitialPhase': None,
            u'horizontalSymmetry': 1,
            u'length': None,
            u'longitudinalPosition': None,
            u'period': None,
            u'verticalAmplitude': None,
            u'verticalInitialPhase': None,
            u'verticalSymmetry': 1,
        }

        gaussianBeam = {
            u'energyPerPulse': _default_value('gbm_pen', v, std_options),
            u'polarization': _default_value('gbm_pol', v, std_options),
            u'rmsPulseDuration': _default_value('gbm_st', v, std_options) * 1e12,
            u'rmsSizeX': _default_value('gbm_sx', v, std_options) * 1e6,
            u'rmsSizeY': _default_value('gbm_sy', v, std_options) * 1e6,
            u'waistAngleX': _default_value('gbm_xp', v, std_options),
            u'waistAngleY': _default_value('gbm_yp', v, std_options),
            u'waistX': _default_value('gbm_x', v, std_options),
            u'waistY': _default_value('gbm_y', v, std_options),
            u'waistZ': _default_value('gbm_z', v, std_options),
        }

    python_dict = {
        u'models': {
            u'beamline': beamlines_list,
            u'electronBeam': electronBeam,
            u'electronBeams': [],
            u'fluxReport': {
                u'azimuthalPrecision': v.sm_pra,
                u'distanceFromSource': v.op_r,
                u'finalEnergy': v.sm_ef,
                u'fluxType': v.sm_type,
                u'horizontalApertureSize': v.sm_rx * 1e3,
                u'horizontalPosition': v.sm_x,
                u'initialEnergy': v.sm_ei,
                u'longitudinalPrecision': v.sm_prl,
                u'photonEnergyPointCount': v.sm_ne,
                u'polarization': v.sm_pol,
                u'verticalApertureSize': v.sm_ry * 1e3,
                u'verticalPosition': v.sm_y,
            },
            u'initialIntensityReport': initialIntensityReport,
            u'intensityReport': {
                u'distanceFromSource': v.op_r,
                u'fieldUnits': 1,
                u'finalEnergy': v.ss_ef,
                u'horizontalPosition': v.ss_x,
                u'initialEnergy': v.ss_ei,
                u'photonEnergyPointCount': v.ss_ne,
                u'polarization': v.ss_pol,
                u'precision': v.ss_prec,
                u'verticalPosition': v.ss_y,
            },
            u'multiElectronAnimation': {
                u'horizontalPosition': 0,
                u'horizontalRange': v.w_rx * 1e3,
                u'stokesParameter': '0',
                u'verticalPosition': 0,
                u'verticalRange': v.w_ry * 1e3,
            },
            u'multipole': {
                u'distribution': 'n',
                u'field': 0,
                u'length': 0,
                u'order': 1,
            },
            u'postPropagation': op.arProp[-1],
            u'powerDensityReport': {
                u'distanceFromSource': v.op_r,
                u'horizontalPointCount': v.pw_nx,
                u'horizontalPosition': v.pw_x,
                u'horizontalRange': v.pw_rx * 1e3,
                u'method': v.pw_meth,
                u'precision': v.pw_pr,
                u'verticalPointCount': v.pw_ny,
                u'verticalPosition': v.pw_y,
                u'verticalRange': v.pw_ry * 1e3,
            },
            u'propagation': get_propagation(op),
            u'simulation': {
                u'facility': 'Import',  # unicode(v.ebm_nm.split()[0]),
                u'horizontalPointCount': v.w_nx,
                u'horizontalPosition': v.w_x,
                u'horizontalRange': v.w_rx * 1e3,
                u'isExample': 0,
                u'name': '',
                u'photonEnergy': v.w_e,
                u'sampleFactor': v.w_smpf,
                u'samplingMethod': 1,
                u'simulationId': '',
                u'sourceType': source_type,
                u'verticalPointCount': v.w_ny,
                u'verticalPosition': v.w_y,
                u'verticalRange': v.w_ry * 1e3,
            },
            u'sourceIntensityReport': {
                u'characteristic': v.si_type,  # 0,
                u'distanceFromSource': v.op_r,
                u'fieldUnits': 2,
                u'polarization': v.si_pol,
            },
            # get_json(static_json_url + '/srw-default.json')['models']['sourceIntensityReport'],
            u'undulator': undulator,
            u'gaussianBeam': gaussianBeam,
        },
        u'report': u'',
        u'simulationType': u'srw',
        u'version': unicode(get_json(static_json_url + '/schema-common.json')['version']),
    }

    # Format the key name to be consistent with Sirepo:
    for i in range(len(beamlines_list)):
        if beamlines_list[i]['type'] == 'watch':
            idx = beamlines_list[i]['id']
            python_dict['models'][u'watchpointReport{}'.format(idx)] = initialIntensityReport

    return python_dict


class SRWParser(object):
    def __init__(self, script, lib_dir, user_filename, arguments):
        self.lib_dir = lib_dir
        self.initial_lib_dir = lib_dir
        self.list_of_files = None
        m = pkrunpy.run_path_as_module(script)
        varParam = getattr(m, 'varParam')
        if arguments:
            import shlex
            arguments = shlex.split(arguments)
        self.var_param = srwl_uti_parse_options(varParam, use_sys_argv=False, arguments=arguments)
        self.get_files()
        if self.initial_lib_dir:
            self.replace_files()
        self.optics = getattr(m, 'set_optics')(self.var_param)
        self.data = parsed_dict(self.var_param, self.optics)
        self.data['models']['simulation']['name'] = _name(user_filename)

    def get_files(self):
        self.list_of_files = []
        for key in self.var_param.__dict__.keys():
            if key.find('_ifn') >= 0:
                self.list_of_files.append(self.var_param.__dict__[key])
            # TODO(robnagler) this directory has to be a constant; imports
            #   don't have control of their environment
            if key.find('fdir') >= 0:
                self.lib_dir = py.path.local(self.var_param.__dict__[key])

    def replace_files(self):
        for key in self.var_param.__dict__.keys():
            if key.find('_ifn') >= 0:
                if getattr(self.var_param, key) != '':
                    self.var_param.__dict__[key] = ''  # 'mirror_1d.dat'
            if key.find('fdir') >= 0:
                self.var_param.__dict__[key] = str(self.initial_lib_dir)
        self.get_files()


def _name(user_filename):
    """Parse base name from user_filename

    Can't assume the file separators will be understood so have to
    parse out the name manually.

    Will need to be uniquely named by sirepo.server, but not done
    yet.

    Args:
        user_filename (str): Passed in from browser

    Returns:
        str: suitable name
    """
    # crude but good enough for now.
    m = re.search(r'([^:/\\]+)\.\w+$', user_filename)
    res = m.group(1) if m else user_filename
    # res could technically
    return res + ' (imported)'


def _find_line_in_trace(script):
    """Parse the stack trace for the most recent error message

    Returns:
        int: first line number in trace that was called from the script
    """
    trace = None
    t = None
    f = None
    try:
        trace = inspect.trace()
        for t in reversed(trace):
            f = t[0]
            if py.path.local(f.f_code.co_filename) == script:
                return f.f_lineno
    finally:
        del trace
        del f
        del t
    return None
