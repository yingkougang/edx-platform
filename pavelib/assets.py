"""
Asset compilation and collection.
"""

from __future__ import print_function

import argparse
import glob
import traceback

from paver import tasks
from paver.easy import sh, path, task, cmdopts, needs, consume_args, call_task, no_help
from watchdog.observers import Observer
from watchdog.events import PatternMatchingEventHandler

from .utils.envs import Env
from .utils.cmd import cmd, django_cmd

# setup baseline paths

COFFEE_DIRS = ['lms', 'cms', 'common']
# A list of directories.  Each will be paired with a sibling /css directory.
SASS_DIRS = [
    path("lms/static/sass"),
    path("lms/static/themed_sass"),
    path("cms/static/sass"),
    path("common/static/sass"),
    path("lms/static/certificates/sass"),
]
SASS_LOAD_PATHS = ['common/static', 'common/static/sass']
SASS_CACHE_PATH = '/tmp/sass-cache'


def configure_paths():
    """Configure our paths based on settings.  Called immediately."""
    edxapp_env = Env()
    if edxapp_env.feature_flags.get('USE_CUSTOM_THEME', False):
        theme_name = edxapp_env.env_tokens.get('THEME_NAME', '')
        parent_dir = path(edxapp_env.REPO_ROOT).abspath().parent
        theme_root = parent_dir / "themes" / theme_name
        COFFEE_DIRS.append(theme_root)
        sass_dir = theme_root / "static" / "sass"
        css_dir = theme_root / "static" / "css"
        if sass_dir.isdir():
            css_dir.mkdir_p()
            SASS_DIRS.append(sass_dir)

    if edxapp_env.env_tokens.get("COMPREHENSIVE_THEME_DIR", ""):
        theme_dir = path(edxapp_env.env_tokens["COMPREHENSIVE_THEME_DIR"])
        lms_sass = theme_dir / "lms" / "static" / "sass"
        lms_css = theme_dir / "lms" / "static" / "css"
        if lms_sass.isdir():
            lms_css.mkdir_p()
            SASS_DIRS.append(lms_sass)
        cms_sass = theme_dir / "cms" / "static" / "sass"
        cms_css = theme_dir / "cms" / "static" / "css"
        if cms_sass.isdir():
            cms_css.mkdir_p()
            SASS_DIRS.append(cms_sass)

configure_paths()


class CoffeeScriptWatcher(PatternMatchingEventHandler):
    """
    Watches for coffeescript changes
    """
    ignore_directories = True
    patterns = ['*.coffee']

    def register(self, observer):
        """
        register files with observer
        """
        dirnames = set()
        for filename in sh(coffeescript_files(), capture=True).splitlines():
            dirnames.add(path(filename).dirname())
        for dirname in dirnames:
            observer.schedule(self, dirname)

    def on_modified(self, event):
        print('\tCHANGED:', event.src_path)
        try:
            compile_coffeescript(event.src_path)
        except Exception:  # pylint: disable=broad-except
            traceback.print_exc()


class SassWatcher(PatternMatchingEventHandler):
    """
    Watches for sass file changes
    """
    ignore_directories = True
    patterns = ['*.scss']
    ignore_patterns = ['common/static/xmodule/*']

    def register(self, observer):
        """
        register files with observer
        """
        for dirname in SASS_LOAD_PATHS + SASS_DIRS:
            paths = []
            if '*' in dirname:
                paths.extend(glob.glob(dirname))
            else:
                paths.append(dirname)
            for dirname in paths:
                observer.schedule(self, dirname, recursive=True)

    def on_modified(self, event):
        print('\tCHANGED:', event.src_path)
        try:
            compile_sass()      # pylint: disable=no-value-for-parameter
        except Exception:       # pylint: disable=broad-except
            traceback.print_exc()


class XModuleSassWatcher(SassWatcher):
    """
    Watches for sass file changes
    """
    ignore_directories = True
    ignore_patterns = []

    def register(self, observer):
        """
        register files with observer
        """
        observer.schedule(self, 'common/lib/xmodule/', recursive=True)

    def on_modified(self, event):
        print('\tCHANGED:', event.src_path)
        try:
            process_xmodule_assets()
        except Exception:  # pylint: disable=broad-except
            traceback.print_exc()


class XModuleAssetsWatcher(PatternMatchingEventHandler):
    """
    Watches for css and js file changes
    """
    ignore_directories = True
    patterns = ['*.css', '*.js']

    def register(self, observer):
        """
        Register files with observer
        """
        observer.schedule(self, 'common/lib/xmodule/', recursive=True)

    def on_modified(self, event):
        print('\tCHANGED:', event.src_path)
        try:
            process_xmodule_assets()
        except Exception:  # pylint: disable=broad-except
            traceback.print_exc()

        # To refresh the hash values of static xmodule content
        restart_django_servers()


def coffeescript_files():
    """
    return find command for paths containing coffee files
    """
    dirs = " ".join(Env.REPO_ROOT / coffee_dir for coffee_dir in COFFEE_DIRS)
    return cmd('find', dirs, '-type f', '-name \"*.coffee\"')


@task
@no_help
def compile_coffeescript(*files):
    """
    Compile CoffeeScript to JavaScript.
    """
    if not files:
        files = ["`{}`".format(coffeescript_files())]
    sh(cmd(
        "node_modules/.bin/coffee", "--compile", *files
    ))


@task
@no_help
@cmdopts([
    ('debug', 'd', 'Debug mode'),
    ('force', '', 'Force full compilation'),
])
def compile_sass(options):
    """
    Compile Sass to CSS.
    """
    debug = options.get('debug')
    parts = ["sass"]
    parts.append("--update")
    parts.append("--cache-location {cache}".format(cache=SASS_CACHE_PATH))
    parts.append("--default-encoding utf-8")
    if debug:
        parts.append("--sourcemap")
    else:
        parts.append("--style compressed --quiet")
    if options.get('force'):
        parts.append("--force")
    parts.append("--load-path .")
    for load_path in SASS_LOAD_PATHS + SASS_DIRS:
        parts.append("--load-path {path}".format(path=load_path))

    for sass_dir in SASS_DIRS:
        css_dir = sass_dir.parent / "css"
        if css_dir:
            parts.append("{sass}:{css}".format(sass=sass_dir, css=css_dir))
        else:
            parts.append(sass_dir)

    sh(cmd(*parts))

    print("\t\tFinished compiling sass.")


def compile_templated_sass(systems, settings):
    """
    Render Mako templates for Sass files.
    `systems` is a list of systems (e.g. 'lms' or 'studio' or both)
    `settings` is the Django settings module to use.
    """
    for sys in systems:
        if sys == "studio":
            sys = "cms"
        sh(django_cmd(
            sys, settings, 'preprocess_assets',
            '{sys}/static/sass/*.scss'.format(sys=sys),
            '{sys}/static/themed_sass'.format(sys=sys)
        ))
        print("\t\tFinished preprocessing {} assets.".format(sys))


def process_xmodule_assets():
    """
    Process XModule static assets.
    """
    sh('xmodule_assets common/static/xmodule')
    print("\t\tFinished processing xmodule assets.")


def restart_django_servers():
    """
    Restart the django server.

    `$ touch` makes the Django file watcher thinks that something has changed, therefore
    it restarts the server.
    """
    sh(cmd(
        "touch", 'lms/urls.py', 'cms/urls.py',
    ))


def collect_assets(systems, settings):
    """
    Collect static assets, including Django pipeline processing.
    `systems` is a list of systems (e.g. 'lms' or 'studio' or both)
    `settings` is the Django settings module to use.
    """
    for sys in systems:
        sh(django_cmd(sys, settings, "collectstatic --noinput > /dev/null"))
        print("\t\tFinished collecting {} assets.".format(sys))


@task
@cmdopts([('background', 'b', 'Background mode')])
def watch_assets(options):
    """
    Watch for changes to asset files, and regenerate js/css
    """
    # Don't watch assets when performing a dry run
    if tasks.environment.dry_run:
        return

    observer = Observer()

    CoffeeScriptWatcher().register(observer)
    SassWatcher().register(observer)
    XModuleSassWatcher().register(observer)
    XModuleAssetsWatcher().register(observer)

    print("Starting asset watcher...")
    observer.start()
    if not getattr(options, 'background', False):
        # when running as a separate process, the main thread needs to loop
        # in order to allow for shutdown by contrl-c
        try:
            while True:
                observer.join(2)
        except KeyboardInterrupt:
            observer.stop()
        print("\nStopped asset watcher.")


@task
@needs(
    'pavelib.prereqs.install_ruby_prereqs',
    'pavelib.prereqs.install_node_prereqs',
)
@consume_args
def update_assets(args):
    """
    Compile CoffeeScript and Sass, then collect static assets.
    """
    parser = argparse.ArgumentParser(prog='paver update_assets')
    parser.add_argument(
        'system', type=str, nargs='*', default=['lms', 'studio'],
        help="lms or studio",
    )
    parser.add_argument(
        '--settings', type=str, default="devstack",
        help="Django settings module",
    )
    parser.add_argument(
        '--debug', action='store_true', default=False,
        help="Disable Sass compression",
    )
    parser.add_argument(
        '--skip-collect', dest='collect', action='store_false', default=True,
        help="Skip collection of static assets",
    )
    parser.add_argument(
        '--watch', action='store_true', default=False,
        help="Watch files for changes",
    )
    args = parser.parse_args(args)

    compile_templated_sass(args.system, args.settings)
    process_xmodule_assets()
    compile_coffeescript()
    call_task('pavelib.assets.compile_sass', options={'debug': args.debug})

    if args.collect:
        collect_assets(args.system, args.settings)

    if args.watch:
        call_task('pavelib.assets.watch_assets', options={'background': not args.debug})
