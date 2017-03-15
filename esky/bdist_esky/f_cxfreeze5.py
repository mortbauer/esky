#  Copyright (c) 2009-2010, Cloud Matrix Pty. Ltd.
#  All rights reserved; available under the terms of the BSD License.
"""

  esky.bdist_esky.f_cxfreeze:  bdist_esky support for cx_Freeze

"""

from builtins import range

import os
import sys
import inspect
import zipfile
import distutils

if sys.platform == "win32":
    from esky import winres


import cx_Freeze
import cx_Freeze.hooks

import esky
from esky.util import is_core_dependency, compile_to_bytecode


def freeze(dist):
    """Freeze the given distribution data using cx_Freeze."""
    includes = dist.includes
    excludes = dist.excludes
    options = dist.freezer_options
    #  Merge in any encludes/excludes given in freezer_options
    for inc in options.pop("includes",()):
        includes.append(inc)
    for exc in options.pop("excludes",()):
        excludes.append(exc)
    if "esky" not in includes and "esky" not in excludes:
        includes.append("esky")
    if "pypy" not in includes and "pypy" not in excludes:
        excludes.append("pypy")
    #  cx_Freeze doesn't seem to respect __path__ properly; hack it so
    #  that the required distutils modules are always found correctly.

    def load_distutils(finder,module):
        module.path = distutils.__path__ + module.path
        finder.IncludeModule("distutils.dist")

    cx_Freeze.hooks.load_distutils = load_distutils
    #  Build kwds arguments out of the given freezer opts.
    kwds = {}
    for (nm,val) in options.items():
        kwds[_normalise_opt_name(nm)] = val
    kwds["includes"] = includes
    kwds["excludes"] = excludes
    kwds["targetDir"] = dist.freeze_dir
    kwds["zipIncludePackages"] = ["encodings"]
    if 'optimize' in kwds:
        kwds["optimizeFlag"] = kwds.pop('optimize')
    #  Build an Executable object for each script.
    #  To include the esky startup code, we write each to a tempdir.
    executables = []
    for exe in dist.get_executables():
        base = None
        if exe.gui_only and sys.platform == "win32":
            base = "Win32GUI"
        executables.append(cx_Freeze.Executable(exe.script,
                                                base=base,
                                                targetName=exe.name,
                                                icon=exe.icon,
                                                **exe._kwds))
    #  Freeze up the executables
    f = cx_Freeze.Freezer(executables,**kwds)
    f.Freeze()
    #  Copy data files into the freeze dir
    for (src,dst) in dist.get_data_files():
        dst = os.path.join(dist.freeze_dir,dst)
        dstdir = os.path.dirname(dst)
        if not os.path.isdir(dstdir):
            dist.mkpath(dstdir)
        dist.copy_file(src,dst)

    zip_name = "python%s%s.zip" % sys.version_info[:2]
    lib = zipfile.ZipFile(os.path.join(dist.freeze_dir,zip_name),"a")
    for (src,arcnm) in dist.get_package_data():
        lib.write(src,arcnm)
    lib.close()
    #  Create the bootstrap code, using custom code if specified.
    code_source = ["__name__ = '__main__'"]
    esky_name = dist.distribution.get_name()
    code_source.append("__esky_name__ = %r" % (esky_name,))
    code_source.append(inspect.getsource(esky.bootstrap))
    if dist.compile_bootstrap_exes:
        if sys.platform == "win32":
            #  Unfortunately this doesn't work, because the cxfreeze exe
            #  contains frozen modules that are inaccessible to a bootstrapped
            #  interpreter.  Disabled until I figure out a workaround. :-(
            pass
            #  The pypy-compiled bootstrap exe will try to load a python env
            #  into its own process and run this "take2" code to bootstrap.
            #take2_code = code_source[1:]
            #take2_code.append(_CUSTOM_WIN32_CHAINLOADER)
            #take2_code.append(dist.get_bootstrap_code())
            #take2_code = compile("\n".join(take2_code),"<string>","exec")
            #take2_code = marshal.dumps(take2_code)
            #clscript = "import marshal; "
            #clscript += "exec marshal.loads(%r); " % (take2_code,)
            #clscript = clscript.replace("%","%%")
            #clscript += "chainload(\"%s\")"
            #  Here's the actual source for the compiled bootstrap exe.
            #from esky.bdist_esky import pypy_libpython
            #code_source.append(inspect.getsource(pypy_libpython))
            #code_source.append("_PYPY_CHAINLOADER_SCRIPT = %r" % (clscript,))
            #code_source.append(_CUSTOM_PYPY_CHAINLOADER)
        code_source.append(dist.get_bootstrap_code())
        code_source = "\n".join(code_source)
        for exe in dist.get_executables(normalise=False):
            if not exe.include_in_bootstrap_env:
                continue
            bsexe = dist.compile_to_bootstrap_exe(exe,code_source)
            if sys.platform == "win32":
                fexe = os.path.join(dist.freeze_dir,exe.name)
                winres.copy_safe_resources(fexe,bsexe)
    else:
        code_source.append(dist.get_bootstrap_code())
        code_source.append("bootstrap()")
        code_source = "\n".join(code_source)
        
        eskybscode = compile_to_bytecode(code_source, "esky_bootstrap.py")
        
        #  Copy any core dependencies
        if "fcntl" not in sys.builtin_module_names:
            for nm in os.listdir(dist.freeze_dir):
                if nm.startswith("fcntl"):
                    dist.copy_to_bootstrap_env(nm)
        for nm in os.listdir(dist.freeze_dir):
            if is_core_dependency(nm):
                dist.copy_to_bootstrap_env(nm)
                
        #  Copy the loader program for each script into the bootstrap env, and
        #  append the bootstrapping code to it as a zipfile.

        cdate = (2000,1,1,0,0,0)
        bslib_in_path = os.path.join(dist.freeze_dir,zip_name)
        bslib_in = zipfile.PyZipFile(bslib_in_path,"r",zipfile.ZIP_STORED)
        bslib_out_path = os.path.join(dist.bootstrap_dir,zip_name)
        bslib_out = zipfile.PyZipFile(bslib_out_path,"w",zipfile.ZIP_STORED)
        bslib_out.writestr(zipfile.ZipInfo("esky_bootstrap.pyc",cdate),eskybscode)

        MAINCODE = 'import esky_bootstrap\nesky_bootstrap.bootstrap()'
        for exe in dist.get_executables(normalise=False):
            if exe.include_in_bootstrap_env:
                exepath = dist.copy_to_bootstrap_env(exe.name)
                name,ext = os.path.splitext(exe.name)
                maincode = compile_to_bytecode(MAINCODE, "%s__main__.py"%name)
                bslib_out.writestr(zipfile.ZipInfo("%s__main__.pyc"%name,cdate),maincode)
        names = bslib_out.namelist()
        for zi in bslib_in.infolist():
            buf = bslib_in.read(zi.filename)
            if zi.filename not in names:
                bslib_out.writestr(zi,buf)
        bslib_out.close()
        bslib_in.close()
        dist.add_to_bootstrap_manifest(bslib_out_path)


def _normalise_opt_name(nm):
    """Normalise option names for cx_Freeze.

    This allows people to specify options named like "opt-name" and have
    them converted to the "optName" format used internally by cx_Freeze.
    """
    bits = nm.split("-")
    for i in range(1,len(bits)):
        if bits[i]:
            bits[i] = bits[i][0].upper() + bits[i][1:]
    return "".join(bits)


#  On Windows, execv is flaky and expensive.  If the chainloader is the same
#  python version as the target exe, we can munge sys.path to bootstrap it
#  into the existing process.
if sys.version_info[0] < 3:
    EXEC_STATEMENT = "exec code in globals()"
else:
    EXEC_STATEMENT = "exec(code,globals())"


#  On Windows, execv is flaky and expensive.  Since the pypy-compiled bootstrap
#  exe doesn't have a python runtime, it needs to chainload the one from the
#  target version dir before trying to bootstrap in-process.
_CUSTOM_PYPY_CHAINLOADER = """

_orig_chainload = _chainload
def _chainload(target_dir):
  mydir = dirname(sys.executable)
  pydll = "python%s%s.dll" % sys.version_info[:2]
  if not exists(pathjoin(target_dir,pydll)):
      _orig_chainload(target_dir)
  else:
      py = libpython(pydll)

      #Py_NoSiteFlag = 1;
      #Py_FrozenFlag = 1;
      #Py_IgnoreEnvironmentFlag = 1;

      py.SetPythonHome("")
      py.Initialize()
      # TODO: can't get this through pypy's type annotator.
      # going to fudge it in python instead :-)
      #py.Sys_SetArgv(list(sys.argv))
      syspath = py.GetProgramFullPath() + ";"
      sysfilenm = basename(py.GetProgramFullPath())
      i = 0
      while i < len(sysfilenm) and sysfilenm[i:] != ".exe":
          i += 1
      sysfilenm = sysfilenm[:i]
      sysdir = dirname(py.GetProgramFullPath())
      syspath += sysdir + "\\%s.zip;" % (sysfilenm,)
      syspath += sysdir + "\\library.zip;"
      syspath += sysdir
      py.Sys_SetPath(syspath);
      #  Escape any double-quotes in sys.argv, so we can easily
      #  include it in a python-level string.
      new_argvs = []
      for arg in sys.argv:
          new_argvs.append('"' + arg.replace('"','\\"') + '"')
      new_argv = "[" + ",".join(new_argvs) + "]"
      py.Run_SimpleString("import sys; sys.argv = %s" % (new_argv,))
      py.Run_SimpleString("import sys; sys.frozen = 'cxfreeze'" % (new_argv,))
      globals = py.Dict_New()
      py.Dict_SetItemString(globals,"__builtins__",py.Eval_GetBuiltins())
      esc_target_dir_chars = []
      for c in target_dir:
          if c == "\\\\":
              esc_target_dir_chars.append("\\\\")
          esc_target_dir_chars.append(c)
      esc_target_dir = "".join(esc_target_dir_chars)
      script = _PYPY_CHAINLOADER_SCRIPT % (esc_target_dir,)
      py.Run_String(script,py.file_input,globals)
      py.Finalize()
      sys.exit(0)

"""

