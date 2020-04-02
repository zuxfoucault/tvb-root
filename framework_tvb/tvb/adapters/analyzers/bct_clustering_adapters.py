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
# CITATION:
# When using The Virtual Brain for scientific publications, please cite it as follows:
#
# Paula Sanz Leon, Stuart A. Knock, M. Marmaduke Woodman, Lia Domide,
# Jochen Mersmann, Anthony R. McIntosh, Viktor Jirsa (2013)
# The Virtual Brain: a simulator of primate brain network dynamics.
# Frontiers in Neuroinformatics (7:10. doi: 10.3389/fninf.2013.00010)
#
#
from tvb.core.entities.load import load_entity_by_gid
from tvb.core.entities.model.model_operation import AlgorithmTransientGroup
from tvb.adapters.analyzers.bct_adapters import BaseBCT, BaseUndirected, bct_description, \
    LABEL_CONN_WEIGHTED_UNDIRECTED, LABEL_CONN_WEIGHTED_DIRECTED, BaseBCTForm
from tvb.core.neocom import h5

BCT_GROUP_CLUSTERING = AlgorithmTransientGroup("Clustering Algorithms", "Brain Connectivity Toolbox", "bctclustering")

class ClusteringCoefficientForm(BaseBCTForm):
    @staticmethod
    def get_connectivity_label():
        return "Binary directed connection matrix"

class ClusteringCoefficient(BaseBCT):
    """
    """
    _ui_group = BCT_GROUP_CLUSTERING

    _ui_name = "Clustering Coefficient BD"
    _ui_description = bct_description("clustering_coef_bd.m")
    _matlab_code = "C = clustering_coef_bd(A);"

    def get_form_class(self):
        return ClusteringCoefficientForm


    def launch(self, view_model):
        connectivity = self.get_connectivity(view_model)
        data = {'A': connectivity.weights}

        result = self.execute_matlab(self._matlab_code, data=data)
        measure_index = self.build_connectivity_measure(result, 'C', connectivity, "Clustering Coefficient BD")
        return [measure_index]


class ClusteringCoefficientBU(BaseUndirected):
    """
    """
    _ui_group = BCT_GROUP_CLUSTERING

    _ui_name = "Clustering Coefficient BU"
    _ui_description = bct_description("clustering_coef_bu.m")
    _matlab_code = "C = clustering_coef_bu(A);"

    def launch(self, view_model):
        connectivity = self.get_connectivity(view_model)
        data = {'A': connectivity.weights}

        result = self.execute_matlab(self._matlab_code, data=data)
        measure_index = self.build_connectivity_measure(result, 'C', connectivity, "Clustering Coefficient BU")
        return [measure_index]

class ClusteringCoefficientWUForm(BaseBCTForm):
    @staticmethod
    def get_connectivity_label():
        return LABEL_CONN_WEIGHTED_UNDIRECTED

class ClusteringCoefficientWU(BaseUndirected):
    """
    """
    _ui_group = BCT_GROUP_CLUSTERING
    _ui_connectivity_label = LABEL_CONN_WEIGHTED_UNDIRECTED

    _ui_name = "Clustering Coeficient WU"
    _ui_description = bct_description("clustering_coef_wu.m")
    _matlab_code = "C = clustering_coef_wu(A);"

    def get_form_class(self):
        return ClusteringCoefficientWUForm

    def launch(self, view_model):
        connectivity = self.get_connectivity(view_model)
        data = {'A': connectivity.scaled_weights()}

        result = self.execute_matlab(self._matlab_code, data=data)
        measure_index = self.build_connectivity_measure(result, 'C', connectivity, "Clustering Coefficient WU")
        return [measure_index]

class ClusteringCoefficientWDForm(BaseBCTForm):
    @staticmethod
    def get_connectivity_label():
        return LABEL_CONN_WEIGHTED_DIRECTED

class ClusteringCoefficientWD(ClusteringCoefficient):
    """
    """
    _ui_connectivity_label = LABEL_CONN_WEIGHTED_DIRECTED

    _ui_name = "Clustering Coeficient WD"
    _ui_description = bct_description("clustering_coef_wd.m")
    _matlab_code = "C = clustering_coef_wd(A);"

    def get_form_class(self):
        return ClusteringCoefficientWDForm

    def launch(self, view_model):
        connectivity = self.get_connectivity(view_model)
        data = {'A': connectivity.scaled_weights()}

        result = self.execute_matlab(self._matlab_code, data=data)
        measure_index = self.build_connectivity_measure(result, 'C', connectivity, "Clustering Coefficient WD")
        return [measure_index]

class TransitivityBinaryDirectedForm(BaseBCTForm):
    @staticmethod
    def get_connectivity_label():
        return "Binary directed connection matrix"

class TransitivityBinaryDirected(BaseBCT):
    """
    """
    _ui_group = BCT_GROUP_CLUSTERING
    _ui_connectivity_label = "Binary directed connection matrix:"

    _ui_name = "Transitivity Binary Directed"
    _ui_description = bct_description("transitivity_bd.m")
    _matlab_code = "T = transitivity_bd(A);"

    def get_form_class(self):
        return TransitivityBinaryDirectedForm

    def launch(self, view_model):
        connectivity = self.get_connectivity(view_model)
        data = {'A': connectivity.weights}

        result = self.execute_matlab(self._matlab_code, data=data)
        value = self.build_float_value_wrapper(result, 'T', "Transitivity Binary Directed")
        return [value]

class TransitivityWeightedDirectedForm(BaseBCTForm):
    @staticmethod
    def get_connectivity_label():
        return LABEL_CONN_WEIGHTED_DIRECTED

class TransitivityWeightedDirected(TransitivityBinaryDirected):
    """
    """
    _ui_connectivity_label = LABEL_CONN_WEIGHTED_DIRECTED

    _ui_name = "Transitivity Weighted Directed"
    _ui_description = bct_description("transitivity_wd.m")
    _matlab_code = "T = transitivity_wd(A);"

    def get_form_class(self):
        return TransitivityWeightedDirectedForm

    def launch(self, view_model):
        connectivity = self.get_connectivity(view_model)
        data = {'A': connectivity.scaled_weights()}

        result = self.execute_matlab(self._matlab_code, data=data)
        value = self.build_float_value_wrapper(result, 'T', "Transitivity Weighted Directed")
        return [value]


class TransitivityBinaryUnDirected(BaseUndirected):
    """
    """
    _ui_group = BCT_GROUP_CLUSTERING

    _ui_name = "Transitivity Binary Undirected"
    _ui_description = bct_description("transitivity_bu.m")
    _matlab_code = "T = transitivity_bu(A);"

    def launch(self, view_model):
        connectivity = self.get_connectivity(view_model)
        data = {'A': connectivity.weights}

        result = self.execute_matlab(self._matlab_code, data=data)
        value = self.build_float_value_wrapper(result, 'T', "Transitivity Binary Undirected")
        return [value]

class TransitivityWeightedUnDirectedForm(BaseBCTForm):
    @staticmethod
    def get_connectivity_label():
        return LABEL_CONN_WEIGHTED_UNDIRECTED

class TransitivityWeightedUnDirected(TransitivityBinaryUnDirected):
    """
    """
    _ui_connectivity_label = LABEL_CONN_WEIGHTED_UNDIRECTED

    _ui_name = "Transitivity Weighted undirected"
    _ui_description = bct_description("transitivity_wu.m")
    _matlab_code = "T = transitivity_wu(A);"

    def get_form_class(self):
        return TransitivityWeightedUnDirectedForm

    def launch(self, view_model):
        connectivity = self.get_connectivity(view_model)
        data = {'A': connectivity.scaled_weights()}

        result = self.execute_matlab(self._matlab_code, data=data)
        value = self.build_float_value_wrapper(result, 'T', "Transitivity Weighted Undirected")
        return [value]
