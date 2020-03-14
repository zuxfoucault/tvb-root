#!/usr/bin/env bash

cd ..

rm -Rf dist
mkdir dist

declare -a folders2pack=("framework_tvb" "scientific_library" "externals/tvb_gdist")
if [[ "$1" != "" ]]; then
    echo "Received param: " "$1"
    folders2pack=("$1")
fi


for pipPackage in "${folders2pack[@]}"; do

    echo "============================="
    echo " Packing: " $pipPackage
    echo "============================="

    cd $pipPackage
    python setup.py sdist
    python setup.py bdist_wheel

    if [ -d "../dist/" ]; then
        mv dist/* ../dist/
    else
        mv dist/* ../../dist/
    fi

    rm -R dist
    rm -R build

    if [ -d "../dist/" ]; then
        cd ..
    else
        cd ../..
    fi
done

## Now package tvb-rest-client
cd framework_tvb
mv setup.py setup_bck.py
mv setup_rest_client.py setup.py
python setup.py sdist
python setup.py bdist_wheel
mv setup.py setup_rest_client.py
mv setup_bck.py setup.py
mv dist/* ../dist/
rm -R dist
rm -R build
cd ..

## After manual check, do the actual deploy on Pypi
# twine upload dist/*