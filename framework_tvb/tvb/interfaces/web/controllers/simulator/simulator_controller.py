# -*- coding: utf-8 -*-
#
#
# TheVirtualBrain-Framework Package. This package holds all Data Management, and
# Web-UI helpful to run brain-simulations. To use it, you also need do download
# TheVirtualBrain-Scientific Package (for simulators). See content of the
# documentation-folder for more details. See also http://www.thevirtualbrain.org
#
# (c) 2012-2020, Baycrest Centre for Geriatric Care ("Baycrest") and others
#
# This program is free software: you can redistribute it and/or modify it under the
# terms of the GNU General Public License as published by the Free Software Foundation,
# either version 3 of the License, or (at your option) any later version.
# This program is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
# PARTICULAR PURPOSE.  See the GNU General Public License for more details.
# You should have received a copy of the GNU General Public License along with this
# program.  If not, see <http://www.gnu.org/licenses/>.
#
#
#   CITATION:
# When using The Virtual Brain for scientific publications, please cite it as follows:
#
#   Paula Sanz Leon, Stuart A. Knock, M. Marmaduke Woodman, Lia Domide,
#   Jochen Mersmann, Anthony R. McIntosh, Viktor Jirsa (2013)
#       The Virtual Brain: a simulator of primate brain network dynamics.
#   Frontiers in Neuroinformatics (7:10. doi: 10.3389/fninf.2013.00010)
#
#

import threading
from cherrypy.lib.static import serve_file
from tvb.adapters.datatypes.db.simulation_history import SimulationHistoryIndex
from tvb.adapters.exporters.export_manager import ExportManager
from tvb.adapters.simulator.coupling_forms import get_form_for_coupling
from tvb.adapters.simulator.equation_forms import get_form_for_equation
from tvb.adapters.simulator.model_forms import get_form_for_model
from tvb.adapters.simulator.monitor_forms import get_form_for_monitor
from tvb.adapters.simulator.noise_forms import get_form_for_noise
from tvb.adapters.simulator.range_parameters import SimulatorRangeParameters
from tvb.adapters.simulator.simulator_adapter import SimulatorAdapterForm
from tvb.adapters.simulator.simulator_fragments import *
from tvb.config.init.introspector_registry import IntrospectionRegistry
from tvb.core.adapters.abcadapter import ABCAdapter
from tvb.core.entities.file.files_helper import FilesHelper
from tvb.core.entities.file.simulator.view_model import AdditiveNoiseViewModel, BoldViewModel, RawViewModel
from tvb.core.entities.file.simulator.view_model import SimulatorAdapterModel, IntegratorStochasticViewModel
from tvb.core.entities.filters.chain import FilterChain
from tvb.core.entities.load import load_entity_by_gid
from tvb.core.entities.model.model_burst import BurstConfiguration
from tvb.core.entities.storage import dao
from tvb.core.neocom import h5
from tvb.core.services.burst_service import BurstService
from tvb.core.services.exceptions import BurstServiceException, ServicesBaseException
from tvb.core.services.operation_service import OperationService
from tvb.core.services.simulator_service import SimulatorService
from tvb.interfaces.web.controllers.autologging import traced
from tvb.interfaces.web.controllers.burst.base_controller import BurstBaseController
from tvb.interfaces.web.controllers.decorators import *
from tvb.interfaces.web.controllers.simulator.simulator_fragment_rendering_rules import \
    SimulatorFragmentRenderingRules, POST_REQUEST
from tvb.interfaces.web.controllers.simulator.simulator_wizzard_urls import SimulatorWizzardURLs


@traced
class SimulatorController(BurstBaseController):
    KEY_IS_LOAD_AFTER_REDIRECT = "is_load_after_redirect"
    COPY_NAME_FORMAT = "copy_of_{}"
    BRANCH_NAME_FORMAT = "{}_branch{}"

    def __init__(self):
        BurstBaseController.__init__(self)
        self.last_loaded_form_url = SimulatorWizzardURLs.SET_CONNECTIVITY_URL
        self.range_parameters = SimulatorRangeParameters()
        self.burst_service = BurstService()
        self.simulator_service = SimulatorService()
        self.files_helper = FilesHelper()
        self.cached_simulator_algorithm = self.algorithm_service.get_algorithm_by_module_and_class(
            IntrospectionRegistry.SIMULATOR_MODULE, IntrospectionRegistry.SIMULATOR_CLASS)

    def _update_last_loaded_fragment_url(self, current_url):
        self.last_loaded_form_url = current_url
        common.add2session(common.KEY_LAST_LOADED_FORM_URL, self.last_loaded_form_url)

    @expose_json
    def cancel_or_remove_burst(self, burst_id):
        """
        Cancel or Remove the burst entity given by burst_id (and all linked entities: op, DTs)
        :returns True: if the op was successfully.
        """
        burst_id = int(burst_id)
        op_id, is_group, remove_after_stop = self.burst_service.cancel_or_remove_burst(burst_id)
        return self.cancel_or_remove_operation(op_id, is_group, remove_after_stop)

    def cancel_or_remove_operation(self, operation_id, is_group, remove_after_stop=False):
        """
        Stop the operation given by operation_id. If is_group is true stop all the
        operations from that group.
        """
        # Load before we remove, to have its data in memory here
        burst_config = BurstService.get_burst_for_operation_id(operation_id, is_group)
        result = OperationService.stop_operation(operation_id, is_group, remove_after_stop)

        if remove_after_stop:
            current_burst = common.get_from_session(common.KEY_BURST_CONFIG)
            if (current_burst is not None and burst_config is not None and current_burst.id == burst_config.id and
                    ((current_burst.fk_simulation == operation_id and not is_group) or
                     (current_burst.fk_operation_group == operation_id and is_group))):
                self.reset_simulator_configuration()
        return result

    @expose_page
    @settings
    @context_selected
    def index(self):
        """Get on burst main page"""
        template_specification = dict(mainContent="burst/main_burst", title="Simulation Cockpit",
                                      includedResources='project/included_resources')
        project = common.get_current_project()

        self.last_loaded_form_url = common.get_from_session(common.KEY_LAST_LOADED_FORM_URL)
        if not self.last_loaded_form_url:
            self.last_loaded_form_url = SimulatorWizzardURLs.SET_CONNECTIVITY_URL
            common.add2session(common.KEY_LAST_LOADED_FORM_URL, SimulatorWizzardURLs.SET_CONNECTIVITY_URL)

        burst_config = common.get_from_session(common.KEY_BURST_CONFIG)
        if not burst_config:
            burst_config = BurstConfiguration(project.id)
            common.add2session(common.KEY_BURST_CONFIG, burst_config)

        if burst_config.start_time is not None:
            is_simulator_load = True
            common.add2session(common.KEY_IS_SIMULATOR_LOAD, True)
        else:
            is_simulator_load = common.get_from_session(common.KEY_IS_SIMULATOR_LOAD) or False

        is_simulator_copy = common.get_from_session(common.KEY_IS_SIMULATOR_COPY) or False

        template_specification['burstConfig'] = burst_config
        template_specification['burst_list'] = self.burst_service.get_available_bursts(common.get_current_project().id)
        portlets_list = []  # self.burst_service.get_available_portlets()
        template_specification['portletList'] = portlets_list
        template_specification['selectedPortlets'] = json.dumps(portlets_list)
        is_branch = common.get_from_session(common.KEY_IS_SIMULATOR_BRANCH)

        form = self.prepare_first_fragment()
        rendering_rules = SimulatorFragmentRenderingRules(form, SimulatorWizzardURLs.SET_CONNECTIVITY_URL, None,
                                                          is_simulator_copy, is_simulator_load,
                                                          last_form_url=self.last_loaded_form_url,
                                                          last_request_type=cherrypy.request.method,
                                                          is_first_fragment=True, is_branch=is_branch)
        template_specification.update(**rendering_rules.to_dict())
        return self.fill_default_attributes(template_specification)

    def prepare_first_fragment(self):
        adapter_instance = ABCAdapter.build_adapter(self.cached_simulator_algorithm)
        form = self.algorithm_service.prepare_adapter_form(adapter_instance=adapter_instance,
                                                           project_id=common.get_current_project().id,
                                                           extra_conditions=self._compute_conn_branch_conditions())

        session_stored_simulator = common.get_from_session(common.KEY_SIMULATOR_CONFIG)
        if session_stored_simulator is None:
            session_stored_simulator = SimulatorAdapterModel()
            common.add2session(common.KEY_SIMULATOR_CONFIG, session_stored_simulator)

        form.fill_from_trait(session_stored_simulator)
        return form

    def _compute_conn_branch_conditions(self):
        is_branch = common.get_from_session(common.KEY_IS_SIMULATOR_BRANCH)

        if is_branch:
            simulator = common.get_from_session(common.KEY_SIMULATOR_CONFIG)
            conn = dao.get_datatype_by_gid(simulator.connectivity.hex)

            if conn.number_of_regions:
                return FilterChain(fields=[FilterChain.datatype + '.number_of_regions'],
                                   operations=["=="], values=[conn.number_of_regions])
        return None

    @expose_fragment('simulator_fragment')
    def set_connectivity(self, **data):
        session_stored_simulator = common.get_from_session(common.KEY_SIMULATOR_CONFIG)
        is_simulator_copy = common.get_from_session(common.KEY_IS_SIMULATOR_COPY) or False
        is_simulator_load = common.get_from_session(common.KEY_IS_SIMULATOR_LOAD) or False
        form = SimulatorAdapterForm()

        if cherrypy.request.method == POST_REQUEST:
            self._update_last_loaded_fragment_url(SimulatorWizzardURLs.SET_COUPLING_PARAMS_URL)
            form.fill_from_post(data)
            self.simulator_service.reset_at_connectivity_change(is_simulator_copy, form, session_stored_simulator)
            form.fill_trait(session_stored_simulator)

        next_form = self.algorithm_service.prepare_adapter_form(
            form_instance=get_form_for_coupling(type(session_stored_simulator.coupling))())
        self.range_parameters.coupling_parameters = next_form.get_range_parameters()
        next_form.fill_from_trait(session_stored_simulator.coupling)

        rendering_rules = SimulatorFragmentRenderingRules(next_form, SimulatorWizzardURLs.SET_COUPLING_PARAMS_URL,
                                                          SimulatorWizzardURLs.SET_CONNECTIVITY_URL, is_simulator_copy,
                                                          is_simulator_load, self.last_loaded_form_url,
                                                          cherrypy.request.method)
        return rendering_rules.to_dict()

    @expose_fragment('simulator_fragment')
    def set_coupling_params(self, **data):
        session_stored_simulator = common.get_from_session(common.KEY_SIMULATOR_CONFIG)
        is_simulator_copy = common.get_from_session(common.KEY_IS_SIMULATOR_COPY) or False
        is_simulator_load = common.get_from_session(common.KEY_IS_SIMULATOR_LOAD) or False

        if cherrypy.request.method == POST_REQUEST:
            self._update_last_loaded_fragment_url(SimulatorWizzardURLs.SET_SURFACE_URL)
            form = get_form_for_coupling(type(session_stored_simulator.coupling))()
            form.fill_from_post(data)
            form.fill_trait(session_stored_simulator.coupling)

        surface_fragment = self.algorithm_service.prepare_adapter_form(form_instance=SimulatorSurfaceFragment(),
                                                                       project_id=common.get_current_project().id)
        surface_fragment.fill_from_trait(session_stored_simulator.surface)
        is_branch = common.get_from_session(common.KEY_IS_SIMULATOR_BRANCH)

        rendering_rules = SimulatorFragmentRenderingRules(surface_fragment, SimulatorWizzardURLs.SET_SURFACE_URL,
                                                          SimulatorWizzardURLs.SET_COUPLING_PARAMS_URL,
                                                          is_simulator_copy, is_simulator_load,
                                                          self.last_loaded_form_url, cherrypy.request.method,
                                                          is_branch=is_branch)

        return rendering_rules.to_dict()

    def _prepare_cortex_fragment(self, session_stored_simulator, rendering_rules):
        surface_index = load_entity_by_gid(session_stored_simulator.surface.surface_gid)
        rm_fragment = self.algorithm_service.prepare_adapter_form(
            form_instance=SimulatorRMFragment(surface_index, session_stored_simulator.connectivity),
            project_id=common.get_current_project().id)

        rm_fragment.fill_from_trait(session_stored_simulator.surface)

        rendering_rules.form = rm_fragment
        rendering_rules.form_action_url = SimulatorWizzardURLs.SET_CORTEX_URL
        return rendering_rules.to_dict()

    def _prepare_stimulus_fragment(self, session_stored_simulator, rendering_rules, is_surface_simulation):
        stimuli_fragment = self.algorithm_service.prepare_adapter_form(
            form_instance=SimulatorStimulusFragment(is_surface_simulation), project_id=common.get_current_project().id)

        stimuli_fragment.fill_from_trait(session_stored_simulator)

        rendering_rules.form = stimuli_fragment
        rendering_rules.form_action_url = SimulatorWizzardURLs.SET_STIMULUS_URL
        return rendering_rules.to_dict()

    @expose_fragment('simulator_fragment')
    def set_surface(self, **data):
        session_stored_simulator = common.get_from_session(common.KEY_SIMULATOR_CONFIG)
        is_simulator_copy = common.get_from_session(common.KEY_IS_SIMULATOR_COPY) or False
        is_simulator_load = common.get_from_session(common.KEY_IS_SIMULATOR_LOAD) or False
        is_branch = common.get_from_session(common.KEY_IS_SIMULATOR_BRANCH)

        rendering_rules = SimulatorFragmentRenderingRules(previous_form_action_url=SimulatorWizzardURLs.SET_SURFACE_URL,
                                                          is_simulation_copy=is_simulator_copy,
                                                          is_simulation_readonly_load=is_simulator_load,
                                                          last_form_url=self.last_loaded_form_url,
                                                          last_request_type=cherrypy.request.method,
                                                          is_branch=is_branch)

        if cherrypy.request.method == POST_REQUEST:
            form = SimulatorSurfaceFragment()
            form.fill_from_post(data)
            self.simulator_service.reset_at_surface_change(is_simulator_copy, form, session_stored_simulator)
            form.fill_trait(session_stored_simulator)

            if session_stored_simulator.surface:
                self._update_last_loaded_fragment_url(SimulatorWizzardURLs.SET_CORTEX_URL)
            else:
                self._update_last_loaded_fragment_url(SimulatorWizzardURLs.SET_STIMULUS_URL)

        rendering_rules.is_simulation_copy = is_simulator_copy
        if session_stored_simulator.surface:
            return self.simulator_service.prepare_cortex_fragment(session_stored_simulator, rendering_rules,
                                                                  common.get_current_project().id,
                                                                  SimulatorWizzardURLs.SET_CORTEX_URL)
        return self._prepare_stimulus_fragment(session_stored_simulator, rendering_rules, False,
                                               common.get_current_project().id, SimulatorWizzardURLs.SET_STIMULUS_URL)

    @expose_fragment('simulator_fragment')
    def set_cortex(self, **data):
        session_stored_simulator = common.get_from_session(common.KEY_SIMULATOR_CONFIG)
        is_simulator_copy = common.get_from_session(common.KEY_IS_SIMULATOR_COPY) or False
        is_simulator_load = common.get_from_session(common.KEY_IS_SIMULATOR_LOAD) or False

        if cherrypy.request.method == POST_REQUEST:
            self._update_last_loaded_fragment_url(SimulatorWizzardURLs.SET_STIMULUS_URL)
            rm_fragment = SimulatorRMFragment()
            rm_fragment.fill_from_post(data)
            rm_fragment.fill_trait(session_stored_simulator.surface)

        rendering_rules = SimulatorFragmentRenderingRules(None, None, SimulatorWizzardURLs.SET_CORTEX_URL,
                                                          is_simulator_copy, is_simulator_load,
                                                          self.last_loaded_form_url, cherrypy.request.method)
        return self.prepare_stimulus_fragment(session_stored_simulator, rendering_rules, True,
                                              common.get_current_project(), SimulatorWizzardURLs.SET_STIMULUS_URL)

    @expose_fragment('simulator_fragment')
    def set_stimulus(self, **data):
        session_stored_simulator = common.get_from_session(common.KEY_SIMULATOR_CONFIG)
        is_simulator_copy = common.get_from_session(common.KEY_IS_SIMULATOR_COPY) or False
        is_simulator_load = common.get_from_session(common.KEY_IS_SIMULATOR_LOAD) or False

        if cherrypy.request.method == POST_REQUEST:
            self._update_last_loaded_fragment_url(SimulatorWizzardURLs.SET_MODEL_URL)
            stimuli_fragment = SimulatorStimulusFragment(session_stored_simulator.is_surface_simulation)
            stimuli_fragment.fill_from_post(data)
            stimuli_fragment.fill_trait(session_stored_simulator)

        model_fragment = self.algorithm_service.prepare_adapter_form(form_instance=SimulatorModelFragment())

        model_fragment.fill_from_trait(session_stored_simulator)
        is_branch = common.get_from_session(common.KEY_IS_SIMULATOR_BRANCH)

        rendering_rules = SimulatorFragmentRenderingRules(model_fragment, SimulatorWizzardURLs.SET_MODEL_URL,
                                                          SimulatorWizzardURLs.SET_STIMULUS_URL, is_simulator_copy,
                                                          is_simulator_load, self.last_loaded_form_url,
                                                          cherrypy.request.method, is_model_fragment=True,
                                                          is_surface_simulation=
                                                          session_stored_simulator.is_surface_simulation,
                                                          is_branch=is_branch)

        return rendering_rules.to_dict()

    @expose_fragment('simulator_fragment')
    def set_model(self, **data):
        session_stored_simulator = common.get_from_session(common.KEY_SIMULATOR_CONFIG)
        is_simulator_copy = common.get_from_session(common.KEY_IS_SIMULATOR_COPY) or False
        is_simulator_load = common.get_from_session(common.KEY_IS_SIMULATOR_LOAD) or False

        if cherrypy.request.method == POST_REQUEST:
            self._update_last_loaded_fragment_url(SimulatorWizzardURLs.SET_MODEL_PARAMS_URL)
            form = SimulatorModelFragment()
            form.fill_from_post(data)
            form.fill_trait(session_stored_simulator)

        form = self.algorithm_service.prepare_adapter_form(
            form_instance=get_form_for_model(type(session_stored_simulator.model))())
        self.range_parameters.model_parameters = form.get_range_parameters()
        form.fill_from_trait(session_stored_simulator.model)

        rendering_rules = SimulatorFragmentRenderingRules(form, SimulatorWizzardURLs.SET_MODEL_PARAMS_URL,
                                                          SimulatorWizzardURLs.SET_MODEL_URL, is_simulator_copy,
                                                          is_simulator_load, self.last_loaded_form_url,
                                                          cherrypy.request.method)
        return rendering_rules.to_dict()

    @expose_fragment('simulator_fragment')
    def set_model_params(self, **data):
        session_stored_simulator = common.get_from_session(common.KEY_SIMULATOR_CONFIG)
        is_simulator_copy = common.get_from_session(common.KEY_IS_SIMULATOR_COPY) or False
        is_simulator_load = common.get_from_session(common.KEY_IS_SIMULATOR_LOAD) or False

        if cherrypy.request.method == POST_REQUEST:
            self._update_last_loaded_fragment_url(SimulatorWizzardURLs.SET_INTEGRATOR_URL)
            form = self.algorithm_service.prepare_adapter_form(
                form_instance=get_form_for_model(type(session_stored_simulator.model))())
            form.fill_from_post(data)
            form.fill_trait(session_stored_simulator.model)

        integrator_fragment = self.algorithm_service.prepare_adapter_form(form_instance=SimulatorIntegratorFragment())
        integrator_fragment.integrator.display_subform = False
        integrator_fragment.fill_from_trait(session_stored_simulator)
        is_branch = common.get_from_session(common.KEY_IS_SIMULATOR_BRANCH)

        rendering_rules = SimulatorFragmentRenderingRules(integrator_fragment, SimulatorWizzardURLs.SET_INTEGRATOR_URL,
                                                          SimulatorWizzardURLs.SET_MODEL_PARAMS_URL, is_simulator_copy,
                                                          is_simulator_load, self.last_loaded_form_url,
                                                          cherrypy.request.method, is_branch=is_branch)

        return rendering_rules.to_dict()

    @expose_fragment('simulator_fragment')
    def set_integrator(self, **data):
        session_stored_simulator = common.get_from_session(common.KEY_SIMULATOR_CONFIG)
        is_simulator_copy = common.get_from_session(common.KEY_IS_SIMULATOR_COPY) or False
        is_simulator_load = common.get_from_session(common.KEY_IS_SIMULATOR_LOAD) or False

        if cherrypy.request.method == POST_REQUEST:
            self._update_last_loaded_fragment_url(SimulatorWizzardURLs.SET_INTEGRATOR_PARAMS_URL)
            fragment = SimulatorIntegratorFragment()
            fragment.fill_from_post(data)
            fragment.fill_trait(session_stored_simulator)

        form = self.algorithm_service.prepare_adapter_form(
            form_instance=get_form_for_integrator(type(session_stored_simulator.integrator))())

        if hasattr(form, 'noise'):
            form.noise.display_subform = False
        form.fill_from_trait(session_stored_simulator.integrator)

        rendering_rules = SimulatorFragmentRenderingRules(form, SimulatorWizzardURLs.SET_INTEGRATOR_PARAMS_URL,
                                                          SimulatorWizzardURLs.SET_INTEGRATOR_URL, is_simulator_copy,
                                                          is_simulator_load, self.last_loaded_form_url,
                                                          cherrypy.request.method)
        return rendering_rules.to_dict()

    def _prepare_monitor_form(self, session_stored_simulator, rendering_rules):
        monitor_fragment = self.algorithm_service.prepare_adapter_form(
            form_instance=SimulatorMonitorFragment(session_stored_simulator.is_surface_simulation))
        monitor_fragment.fill_from_trait(session_stored_simulator.monitors)

        rendering_rules.form = monitor_fragment
        rendering_rules.form_action_url = SimulatorWizzardURLs.SET_MONITORS_URL
        is_branch = common.get_from_session(common.KEY_IS_SIMULATOR_BRANCH)
        rendering_rules.is_branch = is_branch
        return rendering_rules.to_dict()

    @expose_fragment('simulator_fragment')
    def set_integrator_params(self, **data):
        session_stored_simulator = common.get_from_session(common.KEY_SIMULATOR_CONFIG)
        is_simulator_copy = common.get_from_session(common.KEY_IS_SIMULATOR_COPY) or False
        is_simulator_load = common.get_from_session(common.KEY_IS_SIMULATOR_LOAD) or False

        if cherrypy.request.method == POST_REQUEST:
            form = get_form_for_integrator(type(session_stored_simulator.integrator))()
            form.fill_from_post(data)
            form.fill_trait(session_stored_simulator.integrator)
            if isinstance(session_stored_simulator.integrator, IntegratorStochasticViewModel):
                self._update_last_loaded_fragment_url(SimulatorWizzardURLs.SET_NOISE_PARAMS_URL)
            else:
                self._update_last_loaded_fragment_url(SimulatorWizzardURLs.SET_MONITORS_URL)

        rendering_rules = SimulatorFragmentRenderingRules(None, None, SimulatorWizzardURLs.SET_INTEGRATOR_PARAMS_URL,
                                                          is_simulator_copy, is_simulator_load,
                                                          self.last_loaded_form_url, cherrypy.request.method,
                                                          is_noise_fragment=False)

        if not isinstance(session_stored_simulator.integrator, IntegratorStochasticViewModel):
            return self._prepare_monitor_form(session_stored_simulator, rendering_rules)

        integrator_noise_fragment = get_form_for_noise(type(session_stored_simulator.integrator.noise))()
        if hasattr(integrator_noise_fragment, 'equation'):
            integrator_noise_fragment.equation.display_subform = False
        self.range_parameters.integrator_noise_parameters = integrator_noise_fragment.get_range_parameters()
        integrator_noise_fragment.fill_from_trait(session_stored_simulator.integrator.noise)

        rendering_rules.form = integrator_noise_fragment
        rendering_rules.form_action_url = SimulatorWizzardURLs.SET_NOISE_PARAMS_URL
        rendering_rules.is_noise_fragment = True
        return rendering_rules.to_dict()

    @expose_fragment('simulator_fragment')
    def set_noise_params(self, **data):
        session_stored_simulator = common.get_from_session(common.KEY_SIMULATOR_CONFIG)
        is_simulator_copy = common.get_from_session(common.KEY_IS_SIMULATOR_COPY) or False
        is_simulator_load = common.get_from_session(common.KEY_IS_SIMULATOR_LOAD) or False

        if cherrypy.request.method == POST_REQUEST:
            form = get_form_for_noise(type(session_stored_simulator.integrator.noise))()
            form.fill_from_post(data)
            form.fill_trait(session_stored_simulator.integrator.noise)
            if isinstance(session_stored_simulator.integrator.noise, AdditiveNoiseViewModel):
                self._update_last_loaded_fragment_url(SimulatorWizzardURLs.SET_MONITORS_URL)
            else:
                self._update_last_loaded_fragment_url(SimulatorWizzardURLs.SET_NOISE_EQUATION_PARAMS_URL)

        rendering_rules = SimulatorFragmentRenderingRules(None, None, SimulatorWizzardURLs.SET_NOISE_PARAMS_URL,
                                                          is_simulator_copy, is_simulator_load,
                                                          self.last_loaded_form_url, cherrypy.request.method)

        if isinstance(session_stored_simulator.integrator.noise, AdditiveNoiseViewModel):
            return self._prepare_monitor_form(session_stored_simulator, rendering_rules)

        equation_form = get_form_for_equation(type(session_stored_simulator.integrator.noise.b))()
        equation_form.equation.data = session_stored_simulator.integrator.noise.b.equation
        equation_form.fill_from_trait(session_stored_simulator.integrator.noise.b)

        rendering_rules.form = equation_form
        rendering_rules.form_action_url = SimulatorWizzardURLs.SET_NOISE_EQUATION_PARAMS_URL
        return rendering_rules.to_dict()

    @expose_fragment('simulator_fragment')
    def set_noise_equation_params(self, **data):
        session_stored_simulator = common.get_from_session(common.KEY_SIMULATOR_CONFIG)
        is_simulator_copy = common.get_from_session(common.KEY_IS_SIMULATOR_COPY) or False
        is_simulator_load = common.get_from_session(common.KEY_IS_SIMULATOR_LOAD) or False

        if cherrypy.request.method == POST_REQUEST:
            self._update_last_loaded_fragment_url(SimulatorWizzardURLs.SET_MONITORS_URL)
            form = get_form_for_equation(type(session_stored_simulator.integrator.noise.b))()
            form.fill_from_post(data)
            form.fill_trait(session_stored_simulator.integrator.noise.b)

        rendering_rules = SimulatorFragmentRenderingRules(None, None,
                                                          SimulatorWizzardURLs.SET_NOISE_EQUATION_PARAMS_URL,
                                                          is_simulator_copy, is_simulator_load,
                                                          self.last_loaded_form_url, cherrypy.request.method)

        return self._prepare_monitor_form(session_stored_simulator, rendering_rules)

    def _prepare_final_fragment(self, session_stored_simulator, rendering_rules):
        session_stored_burst = common.get_from_session(common.KEY_BURST_CONFIG)
        default_simulation_name, simulation_number = BurstService.prepare_name(session_stored_burst,
                                                                               common.get_current_project().id)
        form = self.algorithm_service.prepare_adapter_form(
            form_instance=SimulatorFinalFragment(default_simulation_name=default_simulation_name))

        if cherrypy.request.method != POST_REQUEST:
            simulation_name = session_stored_burst.name
            if simulation_name is None:
                simulation_name = 'simulation_' + str(simulation_number)
            form.fill_from_post({'input_simulation_name_id': simulation_name,
                                 'simulation_length': str(session_stored_simulator.simulation_length)})

        is_branch = common.get_from_session(common.KEY_IS_SIMULATOR_BRANCH)
        form.fill_from_trait(session_stored_simulator)

        rendering_rules.form = form
        rendering_rules.form_action_url = SimulatorWizzardURLs.SETUP_PSE_URL
        rendering_rules.is_launch_fragment = True
        rendering_rules.is_branch = is_branch
        rendering_rules.is_pse_launch = session_stored_burst.is_pse_burst()
        return rendering_rules.to_dict()

    @expose_fragment('simulator_fragment')
    def set_monitors(self, **data):
        session_stored_simulator = common.get_from_session(common.KEY_SIMULATOR_CONFIG)
        is_simulator_copy = common.get_from_session(common.KEY_IS_SIMULATOR_COPY) or False
        is_simulator_load = common.get_from_session(common.KEY_IS_SIMULATOR_LOAD) or False

        if cherrypy.request.method == POST_REQUEST:
            fragment = SimulatorMonitorFragment(is_surface_simulation=session_stored_simulator.is_surface_simulation)
            fragment.fill_from_post(data)

            session_stored_simulator.monitors = self.simulator_service.build_list_of_monitors(fragment.monitors.value,
                                                                                              session_stored_simulator)

        first_monitor_index, last_loaded_fragment_url = self.simulator_service.skip_raw_monitor(
            session_stored_simulator.monitors, SimulatorWizzardURLs.SETUP_PSE_URL,
            SimulatorWizzardURLs.SET_MONITOR_PARAMS_URL)

        if cherrypy.request.method == POST_REQUEST:
            self._update_last_loaded_fragment_url(last_loaded_fragment_url)

        monitor = session_stored_simulator.monitors[first_monitor_index]
        form = self.algorithm_service.prepare_adapter_form(
            form_instance=get_form_for_monitor(type(monitor))(session_stored_simulator),
            project_id=common.get_current_project().id)
        form.fill_from_trait(monitor)

        rendering_rules = SimulatorFragmentRenderingRules(form, last_loaded_fragment_url,
                                                          SimulatorWizzardURLs.SET_MONITORS_URL, is_simulator_copy,
                                                          is_simulator_load, self.last_loaded_form_url,
                                                          cherrypy.request.method)

        if isinstance(monitor, RawViewModel) and len(session_stored_simulator.monitors) == 1:
            return self._prepare_final_fragment(session_stored_simulator, rendering_rules)

        monitor_name = self.simulator_service.prepare_monitor_legend(session_stored_simulator.is_surface_simulation,
                                                                     monitor)

        rendering_rules.form = form
        rendering_rules.form_action_url = last_loaded_fragment_url
        rendering_rules.monitor_name = monitor_name
        return rendering_rules.to_dict()

    def _handle_next_fragment_for_monitors(self, session_stored_simulator, next_monitor, rendering_rules):
        if not next_monitor:
            return self._prepare_final_fragment(session_stored_simulator, rendering_rules)

        next_form = self.algorithm_service.prepare_adapter_form(
            form_instance=get_form_for_monitor(type(next_monitor))(session_stored_simulator),
            project_id=common.get_current_project().id)
        next_form.fill_from_trait(next_monitor)

        form_action_url = self.simulator_service.build_monitor_url(SimulatorWizzardURLs.SET_MONITOR_PARAMS_URL,
                                                 type(next_monitor).__name__)
        monitor_name = self.simulator_service.prepare_monitor_legend(session_stored_simulator.is_surface_simulation, next_monitor)
        rendering_rules.form = next_form
        rendering_rules.form_action_url = form_action_url
        rendering_rules.monitor_name = monitor_name
        return rendering_rules.to_dict()

    @expose_fragment('simulator_fragment')
    def set_monitor_params(self, current_monitor, **data):
        session_stored_simulator = common.get_from_session(common.KEY_SIMULATOR_CONFIG)
        next_monitor, current_monitor_index = self.simulator_service.get_current_index_and_next_monitor(
            session_stored_simulator.monitors, current_monitor)
        monitor = session_stored_simulator.monitors[current_monitor_index]
        is_simulator_copy = common.get_from_session(common.KEY_IS_SIMULATOR_COPY) or False
        is_simulator_load = common.get_from_session(common.KEY_IS_SIMULATOR_LOAD) or False

        if cherrypy.request.method == POST_REQUEST:
            form = get_form_for_monitor(type(monitor))(session_stored_simulator)
            form.fill_from_post(data)
            form.fill_trait(monitor)

            if isinstance(monitor, BoldViewModel):
                last_loaded_fragment_url = self.simulator_service.build_monitor_url(
                    SimulatorWizzardURLs.SET_MONITOR_EQUATION_URL, current_monitor)
            elif next_monitor is not None:
                last_loaded_fragment_url = self.simulator_service.build_monitor_url(
                    SimulatorWizzardURLs.SET_MONITOR_PARAMS_URL, type(next_monitor).__name__)
            else:
                last_loaded_fragment_url = SimulatorWizzardURLs.SETUP_PSE_URL
            self._update_last_loaded_fragment_url(last_loaded_fragment_url)

        rendering_rules = SimulatorFragmentRenderingRules(None, None, None, is_simulator_copy, is_simulator_load,
                                                          self.last_loaded_form_url, cherrypy.request.method)

        if isinstance(monitor, BoldViewModel):
            next_form = get_form_for_equation(type(monitor.hrf_kernel))()
            next_form.fill_from_trait(monitor.hrf_kernel)
            rendering_rules.form = next_form
            rendering_rules.form_action_url = self.simulator_service.build_monitor_url(
                SimulatorWizzardURLs.SET_MONITOR_EQUATION_URL, current_monitor)
            rendering_rules.previous_form_action_url = self.simulator_service.build_monitor_url(
                SimulatorWizzardURLs.SET_MONITOR_PARAMS_URL, current_monitor)
            return rendering_rules.to_dict()

        rendering_rules.previous_form_action_url = self.simulator_service.build_monitor_url(
            SimulatorWizzardURLs.SET_MONITOR_PARAMS_URL, type(monitor).__name__)
        return self._handle_next_fragment_for_monitors(session_stored_simulator,
                                                                        next_monitor, rendering_rules)

    @expose_fragment('simulator_fragment')
    def set_monitor_equation(self, current_monitor, **data):
        session_stored_simulator = common.get_from_session(common.KEY_SIMULATOR_CONFIG)
        next_monitor, current_monitor_index = self.simulator_service.get_current_index_and_next_monitor(
            session_stored_simulator.monitors, current_monitor)
        monitor = session_stored_simulator.monitors[current_monitor_index]
        is_simulator_copy = common.get_from_session(common.KEY_IS_SIMULATOR_COPY) or False
        is_simulator_load = common.get_from_session(common.KEY_IS_SIMULATOR_LOAD) or False

        if cherrypy.request.method == POST_REQUEST:
            if next_monitor is not None:
                last_loaded_fragment_url = self.simulator_service.build_monitor_url(
                    SimulatorWizzardURLs.SET_MONITOR_PARAMS_URL, type(next_monitor).__name__)
                self._update_last_loaded_fragment_url(last_loaded_fragment_url)
            else:
                self._update_last_loaded_fragment_url(SimulatorWizzardURLs.SETUP_PSE_URL)

            form = get_form_for_equation(type(monitor.hrf_kernel))()
            form.fill_from_post(data)
            form.fill_trait(monitor.hrf_kernel)

        previous_form_action_url = self.simulator_service.build_monitor_url(
            SimulatorWizzardURLs.SET_MONITOR_EQUATION_URL, current_monitor)
        rendering_rules = SimulatorFragmentRenderingRules(None, None, previous_form_action_url, is_simulator_copy,
                                                          is_simulator_load, self.last_loaded_form_url,
                                                          cherrypy.request.method)

        return self._handle_next_fragment_for_monitors(session_stored_simulator, next_monitor, rendering_rules)

    @expose_fragment('simulator_fragment')
    def setup_pse(self, **data):
        is_simulator_copy = common.get_from_session(common.KEY_IS_SIMULATOR_COPY) or False
        is_simulator_load = common.get_from_session(common.KEY_IS_SIMULATOR_LOAD) or False
        next_form = self.algorithm_service.prepare_adapter_form(
            form_instance=SimulatorPSEConfigurationFragment(self.range_parameters.get_all_range_parameters()))

        if cherrypy.request.method == POST_REQUEST:
            session_stored_simulator = common.get_from_session(common.KEY_SIMULATOR_CONFIG)
            session_stored_simulator.simulation_length = float(data['simulation_length'])
            burst_config = common.get_from_session(common.KEY_BURST_CONFIG)
            burst_config.name = data['input_simulation_name_id']
            self._update_last_loaded_fragment_url(SimulatorWizzardURLs.SET_PSE_PARAMS_URL)

        param1, param2 = self._handle_range_params_at_loading()
        if param1:
            param_dict = {'pse_param1': param1.name}
            if param2 is not None:
                param_dict['pse_param2'] = param2.name
            next_form.fill_from_post(param_dict)

        rendering_rules = SimulatorFragmentRenderingRules(next_form, SimulatorWizzardURLs.SET_PSE_PARAMS_URL,
                                                          SimulatorWizzardURLs.SETUP_PSE_URL,
                                                          is_simulator_copy, is_simulator_load,
                                                          self.last_loaded_form_url, cherrypy.request.method)
        return rendering_rules.to_dict()

    def _handle_range_params_at_loading(self):
        burst_config = common.get_from_session(common.KEY_BURST_CONFIG)
        all_range_parameters = self.range_parameters.get_all_range_parameters()

        param1, param2 = self.burst_service.handle_range_params_at_loading(burst_config, all_range_parameters)
        return param1, param2

    @expose_fragment('simulator_fragment')
    def set_pse_params(self, **data):
        is_simulator_copy = common.get_from_session(common.KEY_IS_SIMULATOR_COPY) or False
        is_simulator_load = common.get_from_session(common.KEY_IS_SIMULATOR_LOAD) or False
        form = self.algorithm_service.prepare_adapter_form(
            form_instance=SimulatorPSEConfigurationFragment(self.range_parameters.get_all_range_parameters()))
        burst_config = common.get_from_session(common.KEY_BURST_CONFIG)

        if cherrypy.request.method == POST_REQUEST:
            self._update_last_loaded_fragment_url(SimulatorWizzardURLs.LAUNCH_PSE_URL)
            form.fill_from_post(data)

            param1 = form.pse_param1.value
            burst_config.range1 = param1.to_json()
            param2 = None
            if form.pse_param2.value:
                param2 = form.pse_param2.value
                burst_config.range2 = param2.to_json()
        else:
            param1, param2 = self._handle_range_params_at_loading()
        next_form = self.algorithm_service.prepare_adapter_form(form_instance=SimulatorPSERangeFragment(param1, param2))

        rendering_rules = SimulatorFragmentRenderingRules(next_form, SimulatorWizzardURLs.LAUNCH_PSE_URL,
                                                          SimulatorWizzardURLs.SET_PSE_PARAMS_URL,
                                                          is_simulator_copy, is_simulator_load,
                                                          last_form_url=self.last_loaded_form_url,
                                                          is_launch_pse_fragment=True)
        return rendering_rules.to_dict()

    @expose_json
    def launch_pse(self, **data):
        all_range_parameters = self.range_parameters.get_all_range_parameters()
        range_param1, range_param2 = SimulatorPSERangeFragment.fill_from_post(all_range_parameters, **data)
        session_stored_simulator = common.get_from_session(common.KEY_SIMULATOR_CONFIG)

        project = common.get_current_project()
        user = common.get_logged_user()

        burst_config = common.get_from_session(common.KEY_BURST_CONFIG)
        burst_config.start_time = datetime.now()
        burst_config.range1 = range_param1.to_json()
        if range_param2:
            burst_config.range2 = range_param2.to_json()
        burst_config = self.burst_service.prepare_burst_for_pse(burst_config)
        session_stored_simulator.operation_group_gid = uuid.UUID(burst_config.operation_group.gid)
        session_stored_simulator.ranges = json.dumps(burst_config.ranges)

        try:
            thread = threading.Thread(target=self.simulator_service.async_launch_and_prepare_pse,
                                      kwargs={'burst_config': burst_config,
                                              'user': user,
                                              'project': project,
                                              'simulator_algo': self.cached_simulator_algorithm,
                                              'range_param1': range_param1,
                                              'range_param2': range_param2,
                                              'session_stored_simulator': session_stored_simulator})
            thread.start()
            return {'id': burst_config.id}
        except BurstServiceException as e:
            self.logger.exception("Could not launch burst!")
            return {'error': e.message}

    @expose_json
    def launch_simulation(self, launch_mode, **data):
        current_form = SimulatorFinalFragment()
        session_burst_config = common.get_from_session(common.KEY_BURST_CONFIG)
        session_burst_config.range1 = None
        session_burst_config.range2 = None

        try:
            current_form.fill_from_post(data)
        except Exception as exc:
            self.logger.exception(exc)
            return {'error': str(exc)}

        burst_name = current_form.simulation_name.value

        session_stored_simulator = common.get_from_session(common.KEY_SIMULATOR_CONFIG)
        session_stored_simulator.simulation_length = current_form.simulation_length.value

        project = common.get_current_project()
        user = common.get_logged_user()

        if burst_name != 'none_undefined':
            session_burst_config.name = burst_name

        if launch_mode == self.burst_service.LAUNCH_BRANCH:
            parent_burst = session_burst_config.parent_burst_object
            simulation_state_index = dao.get_generic_entity(SimulationHistoryIndex,
                                                            parent_burst.gid, "fk_parent_burst")
            if simulation_state_index is None or len(simulation_state_index) < 1:
                exc = BurstServiceException("Simulation State not found for %s, thus we are unable to branch from "
                                            "it!" % session_burst_config.name)
                self.logger.error(exc)
                raise exc
            session_stored_simulator.history_gid = simulation_state_index[0].gid

        session_burst_config.start_time = datetime.now()
        session_burst_config = dao.store_entity(session_burst_config)

        try:
            thread = threading.Thread(target=self.simulator_service.async_launch_and_prepare_simulation,
                                      kwargs={'burst_config': session_burst_config,
                                              'user': user,
                                              'project': project,
                                              'simulator_algo': self.cached_simulator_algorithm,
                                              'session_stored_simulator': session_stored_simulator})
            thread.start()
            return {'id': session_burst_config.id}
        except BurstServiceException as e:
            self.logger.exception('Could not launch burst!')
            return {'error': e.message}

    @expose_fragment('burst/burst_history')
    def load_burst_history(self):
        """
        Load the available burst that are stored in the database at this time.
        This is one alternative to 'chrome-back problem'.
        """
        session_burst = common.get_from_session(common.KEY_BURST_CONFIG)
        bursts = self.burst_service.get_available_bursts(common.get_current_project().id)
        self.burst_service.populate_burst_disk_usage(bursts)
        return {'burst_list': bursts,
                'selectedBurst': session_burst.id,
                'first_fragment_url': SimulatorFragmentRenderingRules.FIRST_FORM_URL}

    @staticmethod
    def _prepare_last_fragment_by_burst_type(burst_config):
        if burst_config.is_pse_burst():
            return SimulatorWizzardURLs.LAUNCH_PSE_URL
        else:
            return SimulatorWizzardURLs.SETUP_PSE_URL

    @cherrypy.expose
    def get_last_fragment_url(self, burst_config_id):
        burst_config = self.burst_service.load_burst_configuration(burst_config_id)
        common.add2session(common.KEY_BURST_CONFIG, burst_config)
        return self._prepare_last_fragment_by_burst_type(burst_config)

    @expose_fragment('simulator_fragment')
    def load_burst_read_only(self, burst_config_id):
        try:
            burst_config = self.burst_service.load_burst_configuration(burst_config_id)
            common.add2session(common.KEY_BURST_CONFIG, burst_config)
            project = common.get_current_project()
            storage_path = self.files_helper.get_project_folder(project, str(burst_config.fk_simulation))
            simulator = h5.load_view_model(burst_config.simulator_gid, storage_path)

            common.add2session(common.KEY_SIMULATOR_CONFIG, simulator)
            common.add2session(common.KEY_IS_SIMULATOR_LOAD, True)
            common.add2session(common.KEY_IS_SIMULATOR_COPY, False)

            self._update_last_loaded_fragment_url(self._prepare_last_fragment_by_burst_type(burst_config))
            form = self.prepare_first_fragment()
            rendering_rules = SimulatorFragmentRenderingRules(form, SimulatorWizzardURLs.SET_CONNECTIVITY_URL,
                                                              is_simulation_readonly_load=True, is_first_fragment=True)
            return rendering_rules.to_dict()
        except Exception:
            # Most probably Burst was removed. Delete it from session, so that client
            # has a good chance to get a good response on refresh
            self.logger.exception("Error loading burst")
            common.remove_from_session(common.KEY_BURST_CONFIG)
            raise

    @expose_fragment('simulator_fragment')
    def copy_simulator_configuration(self, burst_config_id):
        common.add2session(common.KEY_IS_SIMULATOR_BRANCH, False)
        common.add2session(common.KEY_IS_SIMULATOR_COPY, True)
        form = self._prepare_first_fragment_for_burst_copy(burst_config_id, self.COPY_NAME_FORMAT)
        rendering_rules = SimulatorFragmentRenderingRules(form, SimulatorWizzardURLs.SET_CONNECTIVITY_URL,
                                                          is_simulation_copy=True, is_simulation_readonly_load=True,
                                                          is_first_fragment=True)
        return rendering_rules.to_dict()

    @expose_fragment('simulator_fragment')
    def branch_simulator_configuration(self, burst_config_id):
        common.add2session(common.KEY_IS_SIMULATOR_BRANCH, True)
        common.add2session(common.KEY_IS_SIMULATOR_COPY, False)
        form = self._prepare_first_fragment_for_burst_copy(burst_config_id, self.BRANCH_NAME_FORMAT)
        rendering_rules = SimulatorFragmentRenderingRules(form, SimulatorWizzardURLs.SET_CONNECTIVITY_URL,
                                                          is_simulation_copy=True, is_simulation_readonly_load=True,
                                                          is_first_fragment=True)

        return rendering_rules.to_dict()

    def _prepare_first_fragment_for_burst_copy(self, burst_config_id, burst_name_format):
        burst_config = self.burst_service.load_burst_configuration(burst_config_id)
        burst_config_copy = burst_config.clone()
        count = dao.count_bursts_with_name(burst_config.name, burst_config.fk_project)
        burst_config_copy.name = burst_name_format.format(burst_config.name, count + 1)

        project = common.get_current_project()
        storage_path = self.files_helper.get_project_folder(project, str(burst_config.fk_simulation))
        simulator = h5.load_view_model(burst_config.simulator_gid, storage_path)

        common.add2session(common.KEY_SIMULATOR_CONFIG, simulator)
        common.add2session(common.KEY_IS_SIMULATOR_LOAD, False)
        common.add2session(common.KEY_BURST_CONFIG, burst_config_copy)

        self._update_last_loaded_fragment_url(self._prepare_last_fragment_by_burst_type(burst_config_copy))
        return self.prepare_first_fragment()

    @expose_fragment('simulator_fragment')
    def reset_simulator_configuration(self):
        common.add2session(common.KEY_SIMULATOR_CONFIG, None)
        common.add2session(common.KEY_IS_SIMULATOR_COPY, False)
        common.add2session(common.KEY_IS_SIMULATOR_LOAD, False)
        common.add2session(common.KEY_IS_SIMULATOR_BRANCH, False)

        self._update_last_loaded_fragment_url(SimulatorWizzardURLs.SET_CONNECTIVITY_URL)
        project = common.get_current_project()
        common.add2session(common.KEY_BURST_CONFIG, BurstConfiguration(project.id))

        form = self.prepare_first_fragment()
        rendering_rules = SimulatorFragmentRenderingRules(form, SimulatorWizzardURLs.SET_CONNECTIVITY_URL,
                                                          is_first_fragment=True)
        return rendering_rules.to_dict()

    @expose_json
    def rename_burst(self, burst_id, burst_name):
        """
        Rename the burst given by burst_id, setting it's new name to
        burst_name.
        """
        validation_result = SimulatorFinalFragment.is_burst_name_ok(burst_name)
        if validation_result is True:
            self.burst_service.rename_burst(burst_id, burst_name)
            return {'success': "Simulation successfully renamed!"}
        else:
            self.logger.exception(validation_result)
            return {'error': validation_result}

    @expose_json
    def get_history_status(self, **data):
        """
        For each burst id received, get the status and return it.
        """
        return self.burst_service.update_history_status(json.loads(data['burst_ids']))

    @cherrypy.expose
    @handle_error(redirect=False)
    @check_user
    def export(self, burst_id):
        export_manager = ExportManager()
        export_zip = export_manager.export_simulator_configuration(burst_id)

        result_name = "tvb_simulation_" + str(burst_id) + ".zip"
        return serve_file(export_zip, "application/x-download", "attachment", result_name)

    @expose_fragment("overlay")
    def get_upload_overlay(self):
        template_specification = self.fill_overlay_attributes(None, "Upload", "Simulation ZIP",
                                                              "burst/upload_burst_overlay", "dialog-upload")
        template_specification['first_fragment_url'] = SimulatorWizzardURLs.SET_CONNECTIVITY_URL
        return self.fill_default_attributes(template_specification)

    @cherrypy.expose
    @handle_error(redirect=True)
    @check_user
    @settings
    def load_simulator_configuration_from_zip(self, **data):
        """Upload Simulator from previously exported ZIP file"""
        self.logger.debug("Uploading ..." + str(data))

        try:
            upload_param = "uploadedfile"
            if upload_param in data and data[upload_param]:
                project = common.get_current_project()
                simulator, burst_config = self.simulator_service.load_from_zip(data[upload_param], project)

                common.add2session(common.KEY_BURST_CONFIG, burst_config)
                common.add2session(common.KEY_SIMULATOR_CONFIG, simulator)
                common.add2session(common.KEY_IS_SIMULATOR_COPY, True)
                common.add2session(common.KEY_IS_SIMULATOR_LOAD, False)
                if burst_config.is_pse_burst():
                    self._update_last_loaded_fragment_url(SimulatorWizzardURLs.LAUNCH_PSE_URL)
                else:
                    self._update_last_loaded_fragment_url(SimulatorWizzardURLs.SETUP_PSE_URL)
        except IOError as ioexcep:
            self.logger.exception(ioexcep)
            common.set_warning_message("This ZIP does not contain a complete simulator configuration")
        except ServicesBaseException as excep:
            self.logger.warning(excep.message)
            common.set_warning_message(excep.message)

        raise cherrypy.HTTPRedirect('/burst/')
