# -*- coding: utf-8 -*-
#
#
# TheVirtualBrain-Framework Package. This package holds all Data Management, and 
# Web-UI helpful to run brain-simulations. To use it, you also need do download
# TheVirtualBrain-Scientific Package (for simulators). See content of the
# documentation-folder for more details. See also http://www.thevirtualbrain.org
#
# (c) 2012-2013, Baycrest Centre for Geriatric Care ("Baycrest")
#
# This program is free software; you can redistribute it and/or modify it under 
# the terms of the GNU General Public License version 2 as published by the Free
# Software Foundation. This program is distributed in the hope that it will be
# useful, but WITHOUT ANY WARRANTY; without even the implied warranty of 
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public
# License for more details. You should have received a copy of the GNU General 
# Public License along with this program; if not, you can download it here
# http://www.gnu.org/licenses/old-licenses/gpl-2.0
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

"""
.. moduleauthor:: Lia Domide <lia.domide@codemart.ro>
"""

import unittest
from tvb.tests.framework.adapters.analyzers import timeseries_metrics_adapter_test
from tvb.tests.framework.adapters.exporters import exporters_test
from tvb.tests.framework.adapters.simulator import simulator_adapter_test
from tvb.tests.framework.adapters.uploaders import uploaders_tests_main
from tvb.tests.framework.adapters.visualizers import visualizers_tests_main


def suite():
    """
    Gather all the tests in package 'adapters' in a test suite.
    """
    test_suite = unittest.TestSuite()
    test_suite.addTest(timeseries_metrics_adapter_test.suite())
    test_suite.addTest(exporters_test.suite())
    test_suite.addTest(simulator_adapter_test.suite())
    test_suite.addTest(uploaders_tests_main.suite())
    test_suite.addTest(visualizers_tests_main.suite())
    return test_suite



if __name__ == "__main__":
    #So you can run tests from this package individually.
    TEST_RUNNER = unittest.TextTestRunner()
    TEST_SUITE = suite()
    TEST_RUNNER.run(TEST_SUITE)
    
    
