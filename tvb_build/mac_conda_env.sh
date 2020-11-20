#!/bin/bash

#Install dependencies
conda update -n base -c defaults conda
conda env remove --name mac-distribution
conda create -y --name mac-distribution python=3.7 nomkl numba scipy numpy==1.18.1 networkx scikit-learn cython pip numexpr psutil
conda install -y --name mac-distribution pytest pytest-cov pytest-benchmark pytest-mock matplotlib-base
conda install -y --name mac-distribution psycopg2 pytables scikit-image==0.14.2 simplejson cherrypy docutils werkzeug==0.16.1
conda install -y --name mac-distribution -c conda-forge jupyterlab flask gevent pillow

/WORK/anaconda3/anaconda3/envs/mac-distribution/bin/pip install --upgrade pip
/WORK/anaconda3/anaconda3/envs/mac-distribution/bin/pip install h5py==2.10 formencode cfflib jinja2 nibabel sqlalchemy==1.1.14 sqlalchemy-migrate==0.11.0 allensdk
/WORK/anaconda3/anaconda3/envs/mac-distribution/bin/pip install tvb-gdist typing BeautifulSoup4 subprocess32 flask-restplus python-keycloak mako pyAesCrypt pyunicore
/WORK/anaconda3/anaconda3/envs/mac-distribution/bin/pip install pyobjc
/WORK/anaconda3/anaconda3/envs/mac-distribution/bin/pip install biplist six
/WORK/anaconda3/anaconda3/envs/mac-distribution/bin/pip uninstall python-magic
/WORK/anaconda3/anaconda3/envs/mac-distribution/bin/pip install python-magic-bin==0.4.14
/WORK/anaconda3/anaconda3/envs/mac-distribution/bin/pip install dmgbuild
