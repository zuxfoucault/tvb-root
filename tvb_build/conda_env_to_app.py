import fileinput
import glob
import logging
import os
import re
import shutil
import stat
import sys
import time

import biplist
import magic
from tvb.basic.profile import TvbProfile

logging.basicConfig(stream=sys.stdout, level=logging.WARNING)
logger = logging.getLogger()

# ===============================================================================
# General settings applicable to all apps
# ===============================================================================
TVB_ROOT = os.path.dirname(os.path.dirname(__file__))
# Name of the app
APP_NAME = "tvb"
# The short version string
VERSION = TvbProfile.current.version.BASE_VERSION
# The website in reversered order (domain first, etc.)
IDENTIFIER = "org.thevirtualbrain"
# The author of this package
AUTHOR = "TVB Team"
# Full path to the anaconda environment folder to package
# Make sure it is the full path (and not a relative one, also to the homedir with ~) so this can be
# correctly replaced later. Conda usßes hardcoded paths, which we convert to `/Applications/<APP_NAME>`
CONDA_ENV_PATH = "/WORK/anaconda3/anaconda3/envs/mac-distribution"
# Folders to include from Anaconda environment, if ommitted everything will be copied
# CONDA_FOLDERS = ["lib", "bin", "share", "qsci", "ssl", "translations"]
# Paths of files and folders to remove from the copied anaconda environment,
# relative to the environment's root.
# For instance, this could be the qt4 apps (an app inside an app is useless)
CONDA_EXCLUDE_FILES = [
    'bin/*.app',
    'bin/*.prl',
    'bin/qmake',
    'bin/2to3*',
    'bin/autopoint',
    'conda-meta',
    'include',
    'lib/*.prl',
    'lib/pkg-config',
    'org.freedesktop.dbus-session.plist'
]

CONDA_EXCLUDE_FILES += map(lambda x: f'translations/{x}', [
    'assistant*', 'designer*', 'linguist*', 'qt_*', 'qtbase*', 'qtconnectivity*', 'qtdeclarative*',
    'qtlocation*', 'qtmultimedia*', 'qtquickcontrols*', 'qtscript*', 'qtserialport*',
    'qtwebsockets*', 'qtxmlpatterns*'
])

# Path to the icon of the app
ICON_PATH = os.path.join(TVB_ROOT, "tvb_build", "icon.icns")
# The entry script of the application in the environment's bin folder
ENTRY_SCRIPT = "-m tvb_bin.app"
# Folder to place created APP and DMG in.
OUTPUT_FOLDER = os.path.join(TVB_ROOT, "dist")

# Information about file types that the app can handle
APP_SUPPORTED_FILES = {
    "CFBundleDocumentTypes": [
        {
            'CFBundleTypeName': "TVB Distribution",
            'CFBundleTypeRole': "Editor",
            'LSHandlerRank': "Owner",
            'CFBundleTypeIconFile': os.path.basename(ICON_PATH),
            'LSItemContentTypes': ["nl.cogsci.osdoc.osexp"],
            'NSExportableTypes': ["nl.cogsci.osdoc.osexp"]
        }
    ],
    "UTExportedTypeDeclarations": [
        {
            'UTTypeConformsTo': ['org.gnu.gnu-zip-archive'],
            'UTTypeDescription': "TVB Distribution",
            'UTTypeIdentifier': "nl.cogsci.osdoc.osexp",
            'UTTypeTagSpecification': {
                'public.filename-extension': 'osexp',
                'public.mime-type': 'application/gzip'
            }
        }
    ]
}
# Placed here to not let linter go crazy. Will be overwritten by main program
RESOURCE_DIR = ""

# Optional config entries
try:
    ICON_PATH = os.path.expanduser(ICON_PATH)
    ICON_FILE = os.path.basename(ICON_PATH)
except NameError:
    ICON_FILE = None

# Account for relative paths to home folder
CONDA_ENV_PATH = os.path.expanduser(CONDA_ENV_PATH)
OUTPUT_FOLDER = os.path.expanduser(OUTPUT_FOLDER)

# Physical location of the app
APP_FILE = os.path.join(OUTPUT_FOLDER, APP_NAME + u'.app')
# Set up the general structure of the app
MACOS_DIR = os.path.join(APP_FILE, u'Contents/MacOS')
# Create APP_NAME/Contents/Resources
RESOURCE_DIR = os.path.join(APP_FILE, u'Contents/Resources')
# Execution script in app
APP_SCRIPT = os.path.join(MACOS_DIR, APP_NAME)


def find_and_replace(path, search, replace, exclusions=None):
    if not type(exclusions) in ['list', 'tuple']:
        exclusions = []

    exclusionValid = False
    for root, _, files in os.walk(path):
        for entry in exclusions:
            if entry in root:
                exclusionValid = True
                break
        if exclusionValid:
            continue
        # Do not traverse into python site-packages folders
        logger.debug('Scanning {}'.format(root))
        candidates = []
        for f in files:
            fullPath = os.path.join(root, f)

            try:
                filetype = magic.from_file(fullPath)
            except UnicodeDecodeError:
                logger.warning(f'Unable to infer type of {fullPath}')
                continue

            if filetype == 'empty':
                continue

            if re.search(r'\stext(?:\s+executable)?', filetype):
                candidates.append(fullPath)

        if len(candidates) == 0:
            continue

        logger.debug(list(map(os.path.basename, candidates)))

        with fileinput.input(candidates, inplace=True) as stream:
            finished = False
            while not finished:
                try:
                    for line in stream:
                        print(line.replace(search, replace), end='')
                    finished = True
                except Exception as e:
                    logger.warning(f'Unable to process: {stream.filename()} - {e}')
                    stream.nextfile()


def replace_conda_abs_paths():
    app_path = os.path.join(os.path.sep, 'Applications', APP_NAME + '.app', 'Contents', 'Resources')
    print('Replacing occurences of {} with {}'.format(CONDA_ENV_PATH, app_path))
    find_and_replace(
        RESOURCE_DIR,
        CONDA_ENV_PATH,
        app_path,
        exclusions=['site-packages', 'doc']
    )


def create_app():
    print("Output Dir {}".format(OUTPUT_FOLDER))
    """ Create an app bundle """

    if os.path.exists(APP_FILE):
        shutil.rmtree(APP_FILE)

    print("\n++++++++++++++++++++++++ Creating APP +++++++++++++++++++++++++++")
    start_t = time.time()

    create_app_structure()
    copy_anaconda_env()
    if ICON_FILE:
        copy_icon()
    create_plist()

    # Do some package specific stuff, which is defined in the extra() function
    # in settings.py (and was imported at the top of this module)
    if "extra" in globals() and callable(extra):
        print("Performing application specific actions.")
        extra()

    replace_conda_abs_paths()

    print("============ APP CREATION FINISHED in {} seconds ====================".format(int(time.time() - start_t)))


def create_app_structure():
    """ Create folder structure comprising a Mac app """
    print("Creating app structure")
    try:
        os.makedirs(MACOS_DIR)
    except OSError as e:
        print('Could not create app structure: {}'.format(e))
        sys.exit(1)

    print("Creating app entry script")
    with open(APP_SCRIPT, 'w') as fp:
        # Write the contents
        try:
            fp.write("#!/usr/bin/env bash\n"
                     "script_dir=$(dirname \"$(dirname \"$0\")\")\n"
                     "$script_dir/Resources/bin/python "
                     "{} $@".format(ENTRY_SCRIPT))
        except IOError as e:
            logger.exception("Could not create Contents/OpenSesame script")
            sys.exit(1)

    # Set execution flags
    current_permissions = stat.S_IMODE(os.lstat(APP_SCRIPT).st_mode)
    os.chmod(APP_SCRIPT, current_permissions |
             stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def copy_anaconda_env():
    """ Copy anaconda environment """
    print("Copying Anaconda environment (this may take a while)")
    try:
        if "CONDA_FOLDERS" in globals():
            # IF conda folders is specified, copy only those folders.
            for item in CONDA_FOLDERS:
                shutil.copytree(
                    os.path.join(CONDA_ENV_PATH, item),
                    os.path.join(RESOURCE_DIR, item),
                    symlinks=True)
        else:
            # Copy everything
            shutil.copytree(CONDA_ENV_PATH, RESOURCE_DIR, True)
    except OSError as e:
        logger.error("Error copying Anaconda environment: {}".format(e))
        sys.exit(1)

    # Delete unncecessary files (such as all Qt apps included with conda)
    if "CONDA_EXCLUDE_FILES" in globals():
        for excl_entry in CONDA_EXCLUDE_FILES:
            full_path = os.path.join(RESOURCE_DIR, excl_entry)
            # Expand wild cards and such
            filelist = glob.glob(full_path)
            for item in filelist:
                try:
                    if os.path.isdir(item):
                        logger.debug("Removing folder: {}".format(item))
                        shutil.rmtree(item)
                    elif os.path.isfile(item):
                        logger.debug("Removing file: {}".format(item))
                        os.remove(item)
                    else:
                        logger.warning("File not found: {}".format(item))
                except (IOError, OSError) as e:
                    logger.error("WARNING: could not delete {}".format(item))


def copy_icon():
    """ Copy icon to Resources folder """
    global ICON_PATH
    print("Copying icon file")
    try:
        shutil.copy(ICON_PATH, os.path.join(RESOURCE_DIR, ICON_FILE))
    except OSError as e:
        logger("Error copying icon file from {}: {}".format(ICON_PATH))


def create_plist():
    print("Creating Info.plist")

    global ICON_FILE
    global VERSION

    if 'LONG_VERSION' in globals():
        global LONG_VERSION
    else:
        LONG_VERSION = VERSION

    info_plist_data = {
        'CFBundleDevelopmentRegion': 'en',
        'CFBundleExecutable': APP_NAME,
        'CFBundleIdentifier': IDENTIFIER,
        'CFBundleInfoDictionaryVersion': '6.0',
        'CFBundleName': APP_NAME,
        'CFBundleDisplayName': APP_NAME,
        'CFBundlePackageType': 'APPL',
        'CFBundleVersion': LONG_VERSION,
        'CFBundleShortVersionString': VERSION,
        'CFBundleSignature': '????',
        'LSMinimumSystemVersion': '10.7.0',
        'LSUIElement': False,
        'NSAppTransportSecurity': {'NSAllowsArbitraryLoads': True},
        'NSHumanReadableCopyright': "(c) 2012-2020, Baycrest Centre for Geriatric Care ('Baycrest') and others",
        'NSMainNibFile': 'MainMenu',
        'NSPrincipalClass': 'NSApplication',
        'NSHighResolutionCapable': True,
    }

    if ICON_FILE:
        info_plist_data['CFBundleIconFile'] = ICON_FILE

    if 'APP_SUPPORTED_FILES' in globals():
        global APP_SUPPORTED_FILES
        info_plist_data['CFBundleDocumentTypes'] = APP_SUPPORTED_FILES['CFBundleDocumentTypes']

        if 'UTExportedTypeDeclarations' in APP_SUPPORTED_FILES:
            info_plist_data['UTExportedTypeDeclarations'] = \
                APP_SUPPORTED_FILES['UTExportedTypeDeclarations']

    biplist.writePlist(info_plist_data, os.path.join(APP_FILE, 'Contents',
                                                     'Info.plist'), binary=False)


if __name__ == "__main__":
    create_app()
