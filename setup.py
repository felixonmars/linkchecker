#!/usr/bin/python2.4
# -*- coding: iso-8859-1 -*-
# Copyright (C) 2000-2005  Bastian Kleineidam
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 675 Mass Ave, Cambridge, MA 02139, USA.
"""setup file for the distuils module"""

import sys
if not hasattr(sys, "version_info"):
    raise SystemExit, "The installation script of this program requires" + \
                      " Python 2.4.0 or later."
if sys.version_info < (2, 4, 0, 'final', 0):
    raise SystemExit, "The installation script of this program requires" + \
                      " Python 2.4.0 or later."
import os
import platform
import stat
import re
import string
import glob
from distutils.core import setup, Extension, DEBUG
import distutils.dist
from distutils.command.install import install
from distutils.command.install_data import install_data
from distutils.command.build_scripts import build_scripts, first_line_re
from distutils.command.build_ext import build_ext
from distutils.command.build import build
from distutils.command.clean import clean
from distutils.dir_util import remove_tree
from distutils.file_util import write_file
from distutils.dep_util import newer
from distutils import util, log, sysconfig

# cross compile config
cc = os.environ.get("CC")
# directory with cross compiled (for win32) python
win_python_dir = "/home/calvin/src/python23-maint-cvs/dist/src/"
# if we are compiling for or under windows
win_compiling = (os.name == 'nt') or (cc is not None and "mingw32" in cc)
# releases supporting our special .bat files
win_bat_releases = ['NT', 'XP', '2000', '2003Server']


def normpath (path):
    """norm a path name to platform specific notation"""
    return os.path.normpath(path)


def cnormpath (path):
    """norm a path name to platform specific notation, but honoring
       the win_compiling flag"""
    path = normpath(path)
    if win_compiling:
        # replace slashes with backslashes
        path = path.replace("/", "\\")
    if not os.path.isabs(path):
        path= os.path.join(sys.prefix, path)
    return path


class MyInstall (install, object):

    def run (self):
        super(MyInstall, self).run()
        # we have to write a configuration file because we need the
        # <install_data> directory (and other stuff like author, url, ...)
        # all paths are made absolute by cnormpath()
        data = []
        for d in ['purelib', 'platlib', 'lib', 'headers', 'scripts', 'data']:
            attr = 'install_%s' % d
            if self.root:
                # cut off root path prefix
                cutoff = len(self.root)
                # don't strip the path separator
                if self.root.endswith(os.sep):
                    cutoff -= 1
                val = getattr(self, attr)[cutoff:]
            else:
                val = getattr(self, attr)
            if attr == 'install_data':
                cdir = os.path.join(val, "share", "linkchecker")
                data.append('config_dir = %r' % cnormpath(cdir))
            data.append("%s = %r" % (attr, cnormpath(val)))
	self.distribution.create_conf_file(data, directory=self.install_lib)

    def get_outputs (self):
        """
        Add the generated config file from distribution.create_conf_file()
        to the list of outputs.
        """
        outs = super(MyInstall, self).get_outputs()
        outs.append(self.distribution.get_conf_filename(self.install_lib))
        return outs

    # compatibility bugfix for Python << 2.5, << 2.4.1, << 2.3.5
    # remove this method when depending on one of the above versions
    def dump_dirs (self, msg):
        if DEBUG:
            from distutils.fancy_getopt import longopt_xlate
            print msg + ":"
            for opt in self.user_options:
                opt_name = opt[0]
                if opt_name[-1] == "=":
                    opt_name = opt_name[0:-1]
                if self.negative_opt.has_key(opt_name):
                    opt_name = string.translate(self.negative_opt[opt_name],
                                                longopt_xlate)
                    val = not getattr(self, opt_name)
                else:
                    opt_name = string.translate(opt_name, longopt_xlate)
                    val = getattr(self, opt_name)
                print "  %s: %s" % (opt_name, val)


class MyInstallData (install_data, object):
    """
    My own data installer to handle permissions.
    """

    def run (self):
        """
        Adjust permissions on POSIX systems.
        """
        super(MyInstallData, self).run()
        if os.name == 'posix' and not self.dry_run:
            # Make the data files we just installed world-readable,
            # and the directories world-executable as well.
            for path in self.get_outputs():
                mode = os.stat(path)[stat.ST_MODE]
                if stat.S_ISDIR(mode):
                    mode |= 011
                mode |= 044
                os.chmod(path, mode)


class MyBuildScripts (build_scripts, object):
    """
    My own script builder to handle windows scripts.
    """

    def run (self):
        """
        Copy each script, and set execute permissions on POSIX systems.
        """
        if not self.scripts:
            return
        self.mkpath(self.build_dir)
        outfiles = []
        for script in self.scripts:
            outfiles.append(self.handle_script(util.convert_path(script)))
        if os.name == 'posix':
            for file in outfiles:
                if self.dry_run:
                    log.info("changing mode of %s", file)
                else:
                    oldmode = os.stat(file)[stat.ST_MODE] & 07777
                    newmode = (oldmode | 0555) & 07777
                    if newmode != oldmode:
                        log.info("changing mode of %s from %o to %o",
                                 file, oldmode, newmode)
                        os.chmod(file, newmode)

    def handle_script (self, script):
        """
        Copy script; if it's marked as a Python script in the Unix way
        (first line matches 'first_line_re', ie. starts with "\#!" and
        contains "python"), then adjust the first line to refer to the
        current Python interpreter as we copy.
        On Windows, such scripts get a ".bat" extension.
        """
        adjust = 0
        outfile = os.path.join(self.build_dir, os.path.basename(script))
        if not self.force and not newer(script, outfile):
            log.debug("not copying %s (up-to-date)", script)
            return outfile

        # Always open the file, but ignore failures in dry-run mode --
        # that way, we'll get accurate feedback if we can read the
        # script.
        try:
            f = open(script, "r")
        except IOError:
            if not self.dry_run:
                raise
            f = None
        else:
            first_line = f.readline()
            if not first_line:
                self.warn("%s is an empty file (skipping)" % script)
                return outfile

            match = first_line_re.match(first_line)
            if match:
                adjust = 1
                post_interp = match.group(1) or ''

        if adjust:
            if platform.system() == 'Windows' and \
               platform.release() in win_bat_releases and \
               not outfile.endswith(".bat"):
                outfile += ".bat"
            self.adjust(f, script, post_interp, outfile)
            f.close()
        else:
            f.close()
            self.copy_file(script, outfile)
        return outfile


    def adjust (self, f, script, post_interp, outfile):
        log.info("copying and adjusting %s -> %s", script, self.build_dir)
        if not self.dry_run:
            outf = open(outfile, "w")
            if outfile.endswith('.bat'):
                pat = '@%s%s -x "%%~f0" %%* & exit /b\n'
            else:
                pat = "#!%s%s\n"
            if not sysconfig.python_build:
                outf.write(pat %
                           (self.executable,
                            post_interp))
            else:
                outf.write(pat %
                           (os.path.join(
                    sysconfig.get_config_var("BINDIR"),
                    "python" + sysconfig.get_config_var("EXE")),
                            post_interp))
            outf.writelines(f.readlines())
            outf.close()


class MyDistribution (distutils.dist.Distribution, object):
    """
    Custom distribution class generating config file.
    """

    def run_commands (self):
        """
        Generate config file and run commands.
        """
        cwd = os.getcwd()
        data = []
        data.append('config_dir = %r' % os.path.join(cwd, "config"))
        data.append("install_data = %r" % cwd)
        data.append("install_scripts = %r" % cwd)
        self.create_conf_file(data)
        super(MyDistribution, self).run_commands()

    def get_conf_filename (self, directory):
        """
        Get name for config file.
        """
        return os.path.join(directory, "_%s_configdata.py"%self.get_name())

    def create_conf_file (self, data, directory=None):
        """
        Create local config file from given data (list of lines) in
        the directory (or current directory if not given).
        """
        data.insert(0, "# this file is automatically created by setup.py")
        data.insert(0, "# -*- coding: iso-8859-1 -*-")
        if directory is None:
            directory = os.getcwd()
        filename = self.get_conf_filename(directory)
        # add metadata
        metanames = ("name", "version", "author", "author_email",
                     "maintainer", "maintainer_email", "url",
                     "license", "description", "long_description",
                     "keywords", "platforms", "fullname", "contact",
                     "contact_email", "fullname")
        for name in metanames:
              method = "get_" + name
              val = getattr(self.metadata, method)()
              if isinstance(val, str):
                  val = unicode(val)
              cmd = "%s = %r" % (name, val)
              data.append(cmd)
        # write the config file
        data.append('appname = "LinkChecker"')
        util.execute(write_file, (filename, data),
                     "creating %s" % filename, self.verbose>=1, self.dry_run)


def cc_supports_option (cc, option):
    prog = "int main(){}\n"
    cc_cmd = "%s -E %s -" % (cc[0], option)
    _in, _out = os.popen4(cc_cmd)
    _in.write(prog)
    _in.close()
    while _out.read(): pass
    return _out.close() is None


class MyBuildExt (build_ext, object):

    def build_extensions (self):
        # For gcc 3.x we can add -std=gnu99 to get rid of warnings.
        extra = []
        if self.compiler.compiler_type == 'unix':
            option = "-std=gnu99"
            if cc_supports_option(self.compiler.compiler, option):
                extra.append(option)
        # First, sanity-check the 'extensions' list
        self.check_extensions_list(self.extensions)
        for ext in self.extensions:
            for opt in extra:
                if opt not in ext.extra_compile_args:
                    ext.extra_compile_args.append(opt)
            self.build_extension(ext)


def list_message_files(package, suffix=".po"):
    """
    Return list of all found message files and their installation paths.
    """
    _files = glob.glob("po/*" + suffix)
    _list = []
    for _file in _files:
        # basename (without extension) is a locale name
        _locale = os.path.splitext(os.path.basename(_file))[0]
        _list.append((_file, os.path.join(
            "share", "locale", _locale, "LC_MESSAGES", "%s.mo" % package)))
    return _list


def check_manifest ():
    """
    Snatched from roundup.sf.net.
    Check that the files listed in the MANIFEST are present when the
    source is unpacked.
    """
    try:
        f = open('MANIFEST')
    except:
        print '\n*** SOURCE WARNING: The MANIFEST file is missing!'
        return
    try:
        manifest = [l.strip() for l in f.readlines()]
    finally:
        f.close()
    err = [line for line in manifest if not os.path.exists(line)]
    if err:
        n = len(manifest)
        print '\n*** SOURCE WARNING: There are files missing (%d/%d found)!'%(
            n-len(err), n)
        print 'Missing:', '\nMissing: '.join(err)


class MyBuild (build, object):
    """
    Custom build command.
    """

    def build_message_files (self):
        """
        For each po/*.po, build .mo file in target locale directory.
        """
        for (_src, _dst) in list_message_files(self.distribution.get_name()):
            _build_dst = os.path.join("build", _dst)
            self.mkpath(os.path.dirname(_build_dst))
            self.announce("Compiling %s -> %s" % (_src, _build_dst))
            from linkcheck import msgfmt
            msgfmt.make(_src, _build_dst)

    def run (self):
        check_manifest()
        self.build_message_files()
        build.run(self)


class MyClean (clean, object):
    """
    Custom clean command.
    """

    def run (self):
        if self.all:
            # remove share directory
            directory = os.path.join("build", "share")
            if os.path.exists(directory):
                remove_tree(directory, dry_run=self.dry_run)
            else:
                log.warn("'%s' does not exist -- can't clean it", directory)
        clean.run(self)


# global include dirs
include_dirs = []
# global macros
define_macros = []
# compiler args
extra_compile_args = []
# library directories
library_dirs = []
# libraries
libraries = []
# scripts
scripts = ['linkchecker']
if win_compiling:
    scripts.append('install-linkchecker.py')

if os.name == 'nt':
    # windows does not have unistd.h
    define_macros.append(('YY_NO_UNISTD_H', None))
else:
    extra_compile_args.append("-pedantic")
    if win_compiling:
        # we are cross compiling with mingw
        # add directory for pyconfig.h
        include_dirs.append(win_python_dir)
        # add directory for Python.h
        include_dirs.append(os.path.join(win_python_dir, "Include"))
        # for finding libpythonX.Y.a
        library_dirs.append(win_python_dir)
        libraries.append("python%s" % get_python_version())

myname = "Bastian Kleineidam"
myemail = "calvin@users.sourceforge.net"

data_files = [
         ('share/linkchecker',
             ['config/linkcheckerrc', 'config/logging.conf', ]),
         ('share/linkchecker/examples',
             ['cgi/lconline/leer.html.en', 'cgi/lconline/leer.html.de',
              'cgi/lconline/index.html', 'cgi/lconline/lc_cgi.html.en',
              'cgi/lconline/lc_cgi.html.de', 'cgi/lconline/check.js',
              'cgi/lc.cgi', 'cgi/lc.fcgi', ]),
      ]

if os.name == 'posix':
    data_files.append(('share/man/man1', ['doc/en/linkchecker.1']))
    data_files.append(('share/man/de/man1', ['doc/de/linkchecker.1']))
    data_files.append(('share/man/fr/man1', ['doc/fr/linkchecker.1']))
    data_files.append(('share/linkchecker/examples',
              ['config/linkchecker-completion', 'config/linkcheck-cron.sh']))
elif win_compiling:
    data_files.append(('share/linkchecker/doc',
             ['doc/en/documentation.html',
              'doc/en/index.html',
              'doc/en/install.html',
              'doc/en/other.html',
              'doc/en/upgrading.html',
              'doc/en/lc.css',
              'doc/en/navigation.css',
              'doc/en/shot1.png',
              'doc/en/shot2.png',
              'doc/en/shot1_thumb.jpg',
              'doc/en/shot2_thumb.jpg',
             ]))

setup (name = "linkchecker",
       version = "3.0",
       description = "check websites and HTML documents for broken links",
       keywords = "link,url,checking,verification",
       author = myname,
       author_email = myemail,
       maintainer = myname,
       maintainer_email = myemail,
       url = "http://linkchecker.sourceforge.net/",
       download_url = "http://sourceforge.net/project/showfiles.php?group_id=1913",
       license = "GPL",
       long_description = """Linkchecker features:
o recursive checking
o multithreaded
o output in colored or normal text, HTML, SQL, CSV or a sitemap
  graph in DOT, GML or XML.
o HTTP/1.1, HTTPS, FTP, mailto:, news:, nntp:, Gopher, Telnet and local
  file links support
o restrict link checking with regular expression filters for URLs
o proxy support
o username/password authorization for HTTP, FTP and Telnet
o robots.txt exclusion protocol support
o Cookie support
o i18n support
o a command line interface
o a (Fast)CGI web interface (requires HTTP server)
""",
       distclass = MyDistribution,
       cmdclass = {'install': MyInstall,
                   'install_data': MyInstallData,
                   'build_scripts': MyBuildScripts,
                   'build_ext': MyBuildExt,
                   'build': MyBuild,
                   'clean': MyClean,
                  },
       packages = ['linkcheck', 'linkcheck.logger', 'linkcheck.checker',
                   'linkcheck.dns', 'linkcheck.dns.rdtypes',
                   'linkcheck.dns.rdtypes.ANY', 'linkcheck.dns.rdtypes.IN',
                   'linkcheck.HtmlParser', 'linkcheck.ftpparse', ],
       ext_modules = [Extension('linkcheck.HtmlParser.htmlsax',
                  sources = ['linkcheck/HtmlParser/htmllex.c',
                   'linkcheck/HtmlParser/htmlparse.c',
                   'linkcheck/HtmlParser/s_util.c',
                  ],
                  extra_compile_args = extra_compile_args,
                  library_dirs = library_dirs,
                  libraries = libraries,
                  define_macros = define_macros,
                  include_dirs = include_dirs + \
                                  [normpath("linkcheck/HtmlParser")],
                  ),
                  Extension("linkcheck.ftpparse._ftpparse",
                        ["linkcheck/ftpparse/_ftpparse.c",
                         "linkcheck/ftpparse/ftpparse.c"],
                  extra_compile_args = extra_compile_args,
                  library_dirs = library_dirs,
                  libraries = libraries,
                  define_macros = define_macros,
                  include_dirs = include_dirs + \
                                  [normpath("linkcheck/ftpparse")],
                         ),
                 ],
       scripts = scripts,
       data_files = data_files,
       classifiers = [
        'Topic :: Internet :: WWW/HTTP :: Site Management :: Link Checking',
        'Development Status :: 5 - Production/Stable',
        'License :: OSI Approved :: GNU General Public License (GPL)',
        'Programming Language :: Python',
        'Programming Language :: C',
      ],
)
