"""Cap 2 — Ingeniería mecánica.

Dos capas:
  1. CÁLCULOS rápidos con unidades (pint) y math/sympy: instantáneos, 0 tokens
     de modelo pesado. El cerebro arma la expresión; aquí se evalúa seguro.
  2. PUENTE FEM a FreeCAD (headless, `freecadcmd`): el análisis real (importar
     STEP -> material -> malla -> cargas/restricciones -> CalculiX -> resultados)
     lo GENERA y corre Claude Code iterando, porque la API FEM de FreeCAD es
     densa y depende de versión. Aquí va el "brief" que lo guía y el runner que
     ejecuta un script .py con freecadcmd. Cero GUI, todo por scripts.
"""
from __future__ import annotations
import math
import os
import shutil
import subprocess
import tempfile

# ----------------------------------------------------------------- unidades
_ureg = None


def _units():
    global _ureg
    if _ureg is None:
        import pint
        _ureg = pint.UnitRegistry()
    return _ureg


def convert(value: float, from_unit: str, to_unit: str) -> str:
    """Convierte una cantidad entre unidades (pint). Ej: 100, 'psi', 'MPa'."""
    try:
        u = _units()
        q = (float(value) * u(from_unit)).to(to_unit)
        return f"{value} {from_unit} = {q.magnitude:.6g} {to_unit}, Wilmer."
    except Exception as e:
        return f"No pude convertir eso, Wilmer: {e}"


_toolbox = None


def _toolbox_ns() -> dict:
    """Namespace con TODO el toolbox de ingeniería cargado (lazy, cacheado):
    unidades, mate, y librerías de termo/fluidos/transf. calor/estructural."""
    global _toolbox
    if _toolbox is not None:
        return dict(_toolbox)
    u = _units()
    ns = {"u": u, "ureg": u, "Q_": u.Quantity, "math": math, "pi": math.pi,
          "sqrt": math.sqrt, "sin": math.sin, "cos": math.cos, "tan": math.tan,
          "log": math.log, "log10": math.log10, "exp": math.exp,
          "radians": math.radians, "degrees": math.degrees,
          "abs": abs, "min": min, "max": max, "sum": sum, "round": round,
          "len": len, "range": range, "print": print, "float": float,
          "int": int, "list": list, "dict": dict, "zip": zip, "enumerate": enumerate}
    try:
        import numpy as np
        ns["np"] = np
    except Exception:
        pass
    try:                                  # termodinámica / propiedades de fluidos
        from CoolProp.CoolProp import PropsSI, HAPropsSI
        ns["PropsSI"] = PropsSI          # propiedades (agua/vapor, refrigerantes, gases)
        ns["HAPropsSI"] = HAPropsSI       # aire húmedo (psicrometría, HVAC)
    except Exception:
        pass
    try:                                  # mecánica de fluidos / instalaciones
        import fluids
        ns["fluids"] = fluids
    except Exception:
        pass
    try:                                  # transferencia de calor
        import ht
        ns["ht"] = ht
    except Exception:
        pass
    try:                                  # análisis estructural matricial
        from Pynite import FEModel3D
        ns["FEModel3D"] = FEModel3D
    except Exception:
        pass
    _toolbox = ns
    return dict(ns)


def compute(code: str) -> str:
    """Resuelve un cálculo de ingeniería de CUALQUIER dominio. El cerebro arma el
    código Python usando el toolbox: u (unidades pint), PropsSI/HAPropsSI
    (CoolProp: termo, vapor, refrigerantes, aire húmedo), fluids (mec. fluidos),
    ht (transf. calor), FEModel3D (estructural), math, np. Una expresión devuelve
    su valor; varias líneas deben hacer print() de lo que importe.
    Ej: "PropsSI('H','T',373.15,'Q',1,'Water')/1000" -> entalpía vapor en kJ/kg."""
    import contextlib
    import io
    ns = _toolbox_ns()
    ns["__builtins__"] = {}               # sin builtins peligrosos; solo lo del ns
    try:
        res = eval(code, ns)              # caso expresión simple
        return f"{res}"
    except SyntaxError:
        buf = io.StringIO()               # caso varias líneas: capturamos print()
        try:
            with contextlib.redirect_stdout(buf):
                exec(code, ns)            # cerebro confiable, ns sin builtins
            out = buf.getvalue().strip()
            return out or "Listo (sin salida; usa print para mostrar resultados)."
        except Exception as e:
            return f"No me salió ese cálculo, Wilmer: {e}"
    except Exception as e:
        return f"No me salió ese cálculo, Wilmer: {e}"


def thermo_property(fluid: str, output: str, name1: str, value1: float,
                    name2: str, value2: float) -> str:
    """Propiedad termodinámica vía CoolProp (sin tablas). fluid: 'Water', 'Air',
    'R134a'... output/name: 'T'(K) 'P'(Pa) 'H'(J/kg) 'S'(J/kg/K) 'D'(kg/m3)
    'Q'(calidad 0-1) 'C'(cp). Ej: vapor sat a 100°C -> Water,'H','T',373.15,'Q',1."""
    try:
        from CoolProp.CoolProp import PropsSI
        val = PropsSI(output, name1, float(value1), name2, float(value2), fluid)
        return f"{output} de {fluid} = {val:.6g} (SI), Wilmer."
    except Exception as e:
        return f"No pude sacar esa propiedad, Wilmer: {e}"


# ----------------------------------------------------------------- gráficas
def _plot_dir() -> str:
    """Dónde guardar las gráficas: la carpeta del proyecto activo si la hay,
    si no ~/Documentos/Cálculos Blue."""
    try:
        import workspace
        wd = workspace.active_workdir()
        if wd and os.path.isdir(os.path.expanduser(wd)):
            return os.path.expanduser(wd)
    except Exception:
        pass
    d = os.path.expanduser("~/Documentos/Cálculos Blue")
    os.makedirs(d, exist_ok=True)
    return d


def plot(code: str, title: str = "") -> str:
    """Genera una GRÁFICA de ingeniería: el cerebro arma código Python que dibuja
    con `plt` (matplotlib) usando el toolbox (np, u, PropsSI, fluids, ht...). NO
    hace falta savefig ni show: aquí se guarda la figura como PNG en la carpeta
    del proyecto (o ~/Documentos/Cálculos Blue) y se ABRE con el visor. Devuelve
    la ruta para decirla por voz."""
    import time
    try:
        import matplotlib
        matplotlib.use("Agg")             # sin GUI: render a archivo
        import matplotlib.pyplot as plt
    except Exception as e:
        return f"No tengo matplotlib disponible, Wilmer: {e}"
    ns = _toolbox_ns()
    ns["plt"] = plt
    plt.close("all")
    try:
        exec(code, ns)                    # cerebro confiable (igual que compute)
    except Exception as e:
        plt.close("all")
        return f"No pude armar la gráfica, Wilmer: {e}"
    fig = plt.gcf()
    if not fig.get_axes():
        plt.close("all")
        return ("El código no dibujó nada, Wilmer. Hay que usar plt.plot, "
                "scatter o bar.")
    if title:
        try:
            fig.axes[0].set_title(title)
        except Exception:
            pass
    path = os.path.join(_plot_dir(),
                        f"grafico_{time.strftime('%Y%m%d_%H%M%S')}"
                        f"_{int(time.time() * 1000) % 1000:03d}.png")
    try:
        fig.tight_layout()
    except Exception:
        pass
    try:
        fig.savefig(path, dpi=130)
    except Exception as e:
        plt.close("all")
        return f"No pude guardar la gráfica, Wilmer: {e}"
    plt.close("all")
    try:
        subprocess.Popen(["xdg-open", path], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass
    return f"Gráfica lista y abierta, Wilmer. La guardé en {path}."


# ----------------------------------------------------------------- FreeCAD FEM
_freecadcmd = None
# wrapper CLI de gmsh (del wheel pip): FreeCAD lo usa para mallar headless
GMSH_WRAPPER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bin", "gmsh")


def gmsh_path() -> str:
    """Ruta al ejecutable gmsh que FreeCAD debe usar para mallar (headless)."""
    if os.path.exists(GMSH_WRAPPER) and os.access(GMSH_WRAPPER, os.X_OK):
        return GMSH_WRAPPER
    return shutil.which("gmsh") or ""


def freecadcmd_path() -> str:
    global _freecadcmd
    if _freecadcmd is None:
        _freecadcmd = (shutil.which("freecadcmd") or shutil.which("FreeCADCmd")
                       or shutil.which("freecad.cmd") or "")
    return _freecadcmd


def freecad_available() -> bool:
    return bool(freecadcmd_path())


def ccx_available() -> bool:
    return bool(shutil.which("ccx") or shutil.which("ccx_2.23")
                or shutil.which("CalculiX"))


def run_freecad_script(code: str, workdir: str | None = None,
                       timeout: int = 600) -> dict:
    """Corre un script Python con freecadcmd (headless). Devuelve
    {ok, stdout, stderr}. NO toca ninguna ventana."""
    exe = freecadcmd_path()
    if not exe:
        return {"ok": False, "stdout": "", "stderr": "freecadcmd no encontrado"}
    fd, path = tempfile.mkstemp(suffix=".py", dir=workdir or None, text=True)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(code)
        out = subprocess.run([exe, path], cwd=workdir or None,
                             capture_output=True, text=True, timeout=timeout)
        return {"ok": out.returncode == 0,
                "stdout": out.stdout or "", "stderr": out.stderr or ""}
    except subprocess.TimeoutExpired:
        return {"ok": False, "stdout": "", "stderr": "timeout en freecadcmd"}
    except Exception as e:
        return {"ok": False, "stdout": "", "stderr": str(e)}
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


# triggers de un análisis FEM (lo detecta tasks.detect para delegar a Claude Code)
import re as _re
FEM_TRIGGERS = _re.compile(
    r"\b(an[aá]lisis|anal[ií]za\w*|simula\w*|simulaci[oó]n|malla\w*|mallar|"
    r"elementos\s+finitos|\bfem\b|esfuerz\w*|tensi[oó]n\s+de|deformaci[oó]n\w*|"
    r"factor\s+de\s+seguridad|von\s+mises|importa\w*\s+.*\bstep\b|"
    r"restriccion\w*|cargas?\b)", _re.IGNORECASE)


def is_fem_request(text: str) -> bool:
    return freecad_available() and bool(FEM_TRIGGERS.search(text or ""))


def fem_brief() -> str:
    """Instrucciones + RECETA PROBADA (FreeCAD 1.1 en esta máquina) para que
    Claude Code arme y corra el análisis FEM headless. Se concatena a la tarea."""
    return (
        "\n\nMODO FEM (FreeCAD headless): el usuario pide un ANÁLISIS por "
        "elementos finitos. Trabaja SOLO con scripts corridos por "
        "`freecadcmd <script.py>` (SIN GUI). Esta receta YA FUNCIONA en esta "
        "máquina (FreeCAD 1.1 + gmsh por pip + CalculiX ccx); adáptala a la "
        "geometría/material/cargas reales del usuario, NO la cambies a ciegas:\n"
        "```python\n"
        "import FreeCAD, Part, ObjectsFem\n"
        "from femtools import ccxtools\n"
        "from femmesh.gmshtools import GmshTools\n"
        "# OBLIGATORIO: apuntar FreeCAD al gmsh del venv (si no, la malla sale vacía)\n"
        "FreeCAD.ParamGet('User parameter:BaseApp/Preferences/Mod/Fem/Gmsh')"
        ".SetString('gmshBinaryPath', '" + GMSH_WRAPPER + "')\n"
        "doc = FreeCAD.newDocument('fem')\n"
        "# geometria: importa el STEP del usuario con Import.insert(ruta, doc.Name)\n"
        "# y toma el objeto solido; aqui una caja de ejemplo:\n"
        "box = doc.addObject('Part::Box','Box'); box.Length=1000; box.Width=100; box.Height=100\n"
        "doc.recompute()\n"
        "an = ObjectsFem.makeAnalysis(doc,'Analysis')\n"
        "sol = ObjectsFem.makeSolverCalculiXCcxTools(doc,'CalculiX'); an.addObject(sol)\n"
        "mat = ObjectsFem.makeMaterialSolid(doc,'Mat'); m = mat.Material\n"
        "m['Name']='Steel'; m['YoungsModulus']='210000 MPa'; m['PoissonRatio']='0.30'\n"
        "mat.Material = m; an.addObject(mat)\n"
        "fix = ObjectsFem.makeConstraintFixed(doc,'Fixed'); fix.References=[(box,'Face1')]; an.addObject(fix)\n"
        "frc = ObjectsFem.makeConstraintForce(doc,'Force'); frc.References=[(box,'Face2')]\n"
        "# OJO UNIDADES: la fuerza DEBE ir como Quantity en N (un float se interpreta en mN, sale 1000x mal)\n"
        "frc.Force = FreeCAD.Units.Quantity('1000000 N'); frc.Reversed=False; an.addObject(frc)\n"
        "gm = ObjectsFem.makeMeshGmsh(doc,'Mesh'); gm.Shape=box; gm.CharacteristicLengthMax='50 mm'; an.addObject(gm)\n"
        "GmshTools(gm).create_mesh()\n"
        "assert gm.FemMesh.NodeCount > 0, 'malla vacia'\n"
        "fea = ccxtools.FemToolsCcx(an, sol)\n"
        "fea.update_objects(); fea.setup_working_dir(); fea.setup_ccx()\n"
        "err = fea.check_prerequisites()\n"
        "assert not err, err\n"
        "fea.purge_results(); fea.write_inp_file(); fea.ccx_run(); fea.load_results()\n"
        "for o in an.Group:\n"
        "    if o.isDerivedFrom('Fem::FemResultObject'):\n"
        "        print('DESPLAZ_MAX_mm', round(max(o.DisplacementLengths),4))\n"
        "        print('VONMISES_MAX_MPa', round(max(o.vonMises),2))\n"
        "doc.saveAs('<carpeta_del_proyecto>/analisis.FCStd')\n"
        "```\n"
        "- Identifica las CARAS reales (Face1, Face2, ...) según la geometría del "
        "usuario; para empotrar usa makeConstraintFixed, para cargas "
        "makeConstraintForce (Quantity en N) o makeConstraintPressure (MPa).\n"
        "- Malla más fina (CharacteristicLengthMax menor) donde haya "
        "concentraciones de esfuerzo. Valida siempre contra un cálculo a mano "
        "aproximado (F/A, etc.); si el orden de magnitud no cuadra, revisa "
        "unidades o referencias de cara.\n"
        "- Guarda el .FCStd y un resumen en la carpeta del proyecto. Reporta en "
        "1-3 frases para voz: qué analizaste, von Mises y desplazamiento máx, y "
        "el factor de seguridad si dieron el límite del material. NO inventes "
        "resultados: si no resolvió, dilo."
    )
