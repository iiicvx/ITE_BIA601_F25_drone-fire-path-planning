"""يضيف وصولًا بصيغتي Unicode وOpenType إلى أشكال خط Akhbar MT الأصلي من عام 1993.

الاستخدام (يتطلب fonttools[woff]): python frontend/prepare_akhbar.py source.woff2 output.woff2
الملف القديم لا يحتوي إلا جدول Windows Symbol cmap. نحافظ على خطوطه وتلميحاته
وأسمائه وحقوقه، ونتيح أشكاله العربية السياقية الموجودة لمحركات التشكيل في المتصفحات الحديثة.
لا يُستبدل أي شكل بخط آخر.
"""
import sys
import unicodedata
from pathlib import Path

from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
from fontTools.ttLib import TTFont
from fontTools.ttLib.tables._c_m_a_p import CmapSubtable


def prepare(source, destination):
    font = TTFont(source)
    # رمز المحرف، والشكل المنفرد، والشكل الأخير، والشكل الأول، والشكل الأوسط.
    letters = [
        (0x621, "hamzah", None, None, None),
        (0x622, "maddahonalef", "fnmaddahonalef", None, None),
        (0x623, "hamzahonalef", "fnhamzahonalef", None, None),
        (0x624, "hamzahonwaw", "fnhamzahonwaw", None, None),
        (0x625, "hamzahunderalef", "fnhamzahunderalef", None, None),
        (0x626, "hamzahonyah", "fnhamzahonya", "inhamzahonya", "midhamzahonya"),
    ]
    names = ["alef", "baa", "taamarbutah", "taa", "thaa", "jeem", "haa", "khaa", "dal", "thal", "ra", "zain", "seen", "sheen", "sad", "dad", "tah", "dhah", "ain", "ghain"]
    names += ["tatweelwide", "fa", "qaf", "caf", "lam", "meem", "noon", "ha", "waw", "alefmaqsurah", "ya"]
    glyphs = set(font.getGlyphOrder())
    codes = [*range(0x627, 0x63B), *range(0x640, 0x64B)]
    for code, name in zip(codes, names):
        if name == "tatweelwide":
            letters.append((code, name, None, None, None))
        else:
            letters.append((code, name, *(prefix + name if prefix + name in glyphs else None for prefix in ("fn", "in", "mid"))))
    cmap = {code: name for code, name, *_ in letters}
    marks = ["fathatan", "dammatah", "kasratan", "fathah", "dammah", "kasrah", "shaddah", "sukun"]
    cmap.update({0x64B + i: name for i, name in enumerate(marks)})
    cmap.update({0x660 + i: name + "arabic" for i, name in enumerate(["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"])})
    cmap.update({0x20: "righttoleftspace", 0x60C: "commaarabic", 0x61B: "semicolonarabic", 0x61F: "questionarabic", 0x66A: "percentarabic", 0xFDF2: "Allah"})
    forms = {code: (base, final, initial, medial) for code, base, final, initial, medial in letters}
    ligatures = {0x622: ("maddahonlamelef", "fnmaddahonlamelef"), 0x623: ("hamzahonlamelef", "fnhamzahonlamelef"), 0x625: ("hamzahunderlamelef", "fnhamzahunderlamelef"), 0x627: ("lamelef", "fnlamalef")}
    tags = {"<isolated>": 0, "<final>": 1, "<initial>": 2, "<medial>": 3}
    for code in range(0xFE70, 0xFEFD):
        parts = unicodedata.decomposition(chr(code)).split()
        if parts and parts[0] in tags:
            points = tuple(int(p, 16) for p in parts[1:])
            name = forms.get(points[0], (None,) * 4)[tags[parts[0]]] if len(points) == 1 else None
            if len(points) == 2 and points[0] == 0x644 and points[1] in ligatures:
                name = ligatures[points[1]][tags[parts[0]]]
            if name:
                cmap[code] = name
    font["cmap"].tables = []
    for platform, encoding in [(0, 3), (3, 1)]:
        table = CmapSubtable.newSubtable(4)
        table.platformID, table.platEncID, table.language, table.cmap = platform, encoding, 0, cmap.copy()
        font["cmap"].tables.append(table)
    features = ["languagesystem DFLT dflt; languagesystem arab dflt;", f"@Marks = [{' '.join(marks)}];", "table GDEF { GlyphClassDef , , @Marks, ; } GDEF;"]
    for tag, index in [("fina", 2), ("init", 3), ("medi", 4)]:
        rules = " ".join(f"sub {row[1]} by {row[index]};" for row in letters if row[index])
        features.append(f"feature {tag} {{ {rules} }} {tag};")
    rules = []
    for code, (isolated, final) in ligatures.items():
        alef = forms[code][1]
        rules.extend([f"sub inlam {alef} by {isolated};", f"sub midlam {alef} by {final};"])
    features.append(f"feature rlig {{ lookupflag IgnoreMarks; {' '.join(rules)} }} rlig;")
    addOpenTypeFeaturesFromString(font, "\n".join(features))
    font["OS/2"].ulCodePageRange1 = 1 << 6
    font["OS/2"].recalcUnicodeRanges(font)
    font.flavor = "woff2"
    font.save(destination)
    print(f"{Path(destination).name}: {len(cmap)} Unicode mappings; original Akhbar MT outlines preserved")


if __name__ == "__main__":
    prepare(*sys.argv[1:])
