"""Build real BelG2P phonetic rules as JavaScript using TeaVM.

Only storage/resource access and reflection dispatch are adapted. Phonetic
processes, matching, stress lookup and serialization stay upstream Java code.
Requires Java 21+ and Maven (or --maven /path/to/mvn).
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import urllib.request
import zipfile

import pooch

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'tools/browser_demo/teavm'
OUTPUT = ROOT / 'browser_demo/g2p'


def replace(source, old, new):
    if old not in source:
        raise RuntimeError(f'Upstream source changed: cannot find {old[:80]!r}')
    return source.replace(old, new)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--maven', default='mvn')
    args = parser.parse_args()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    cache = BUILD / 'downloads'
    cache.mkdir(exist_ok=True)
    urls = {
        'belg2p.tar.gz': 'https://github.com/Belarus/BelG2P/archive/refs/tags/1.0.0.tar.gz',
        'grammar-sources.jar': 'https://repo.maven.apache.org/maven2/io/github/belarus/linguistics.grammardb.reader/1.5.0/linguistics.grammardb.reader-1.5.0-sources.jar',
    }
    for name, url in urls.items():
        if not (cache / name).exists():
            urllib.request.urlretrieve(url, cache / name)
    with tarfile.open(cache / 'belg2p.tar.gz') as archive:
        archive.extractall(cache, filter='data')
    upstream = cache / 'BelG2P-1.0.0/src/main'
    generated = BUILD / 'generated'
    generated.mkdir(exist_ok=True)

    def write(name, text):
        dest = generated / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding='utf-8')

    for package in ['config', 'impl', 'processes', 'utils']:
        for f in (upstream / 'java/org/alex73/fanetyka' / package).rglob('*.java'):
            if f.name in ['FanetykaText.java', 'FanetykaTTSPrepare.java']:
                continue
            if package == 'utils' and f.name not in ['ReadResource.java', 'Amohrafy.java']:
                continue
            source = f.read_text()
            # TeaVM has no ExceptionInInitializerError; this only changes the
            # error wrapper, not successful phonetic processing.
            source = source.replace('new ExceptionInInitializerError(', 'new RuntimeException(')
            if f.name == 'ReadResource.java':
                source = source.replace('cls.getResourceAsStream(resourceName)',
                    'new java.io.ByteArrayInputStream(org.belvoice.browser.BrowserG2P.resource('
                    '"/" + cls.getName().substring(0, cls.getName().lastIndexOf(\'.\')).replace(\'.\', \'/\') + "/" + resourceName).getBytes(StandardCharsets.UTF_8))')
                # TeaVM's Properties.load differs on these Unicode sound keys.
                # These upstream files are simple UTF-8 key=value tables.
                source = replace(source, '            props.load(rd);', '''            String line;
            while ((line = rd.readLine()) != null) {
                line = line.trim();
                if (line.isEmpty() || line.startsWith("#")) continue;
                int separator = line.indexOf('=');
                if (separator <= 0) throw new RuntimeException("Invalid sound mapping: " + line);
                String value = line.substring(separator + 1).trim();
                StringBuilder decoded = new StringBuilder();
                for (int i=0; i<value.length(); i++) {
                    if (value.charAt(i) == '\\\\' && i+5<value.length() && value.charAt(i+1)=='u') {
                        decoded.append((char)Integer.parseInt(value.substring(i+2,i+6),16)); i+=5;
                    } else decoded.append(value.charAt(i));
                }
                props.setProperty(line.substring(0,separator).trim(), decoded.toString());
            }''')
            elif f.name == 'FanetykaConfig.java':
                source = source.replace('Collections.sort(debugCases, Collator.getInstance(Locale.of("be")));',
                                        'Collections.sort(debugCases);')
                source = replace(source, 'TsvConfig.class.getResourceAsStream("/" + t + ".tsv")',
                    'new java.io.ByteArrayInputStream(org.belvoice.browser.BrowserG2P.resource("/" + t + ".tsv").getBytes(java.nio.charset.StandardCharsets.UTF_8))')
            elif f.name == 'ProcessRunner.java':
                source = adapt_dispatch(source, upstream)
            elif f.name == 'WordInitialConverter.java':
                # Expose the unchanged pure matcher for the optional ML OOV
                # guard, without constructing sounds or overriding GrammarDB.
                source = replace(source, 'private boolean compareWord(String inputWord, String grammarDbWord)',
                                 'public static boolean compareWord(String inputWord, String grammarDbWord)')
            elif f.name == 'Amohrafy.java':
                source = replace(source, 'Amohrafy.class.getResourceAsStream("amohrafy_naciski.txt")',
                    'new java.io.ByteArrayInputStream(org.belvoice.browser.BrowserG2P.resource("/org/alex73/fanetyka/utils/amohrafy_naciski.txt").getBytes(StandardCharsets.UTF_8))')
            write(str(f.relative_to(upstream / 'java')), source)

    with zipfile.ZipFile(cache / 'grammar-sources.jar') as archive:
        for name in ['StressUtils', 'WordMorphology']:
            path = f'org/alex73/grammardb/{name}.java'
            write(path, archive.read(path).decode())
    write('org/alex73/grammardb/GrammarDB2.java', '''package org.alex73.grammardb;
public class GrammarDB2 {
    public static final char pravilny_nacisk = '\\u0301';
    public static final char pravilny_apostraf = '\\u02BC';
}''')
    # Small storage DTOs replace JAXB objects; all fields used by the original
    # WordMorphology/WordInitialConverter/phonetic rules are preserved.
    classes = {
        'Paradigm': [('int','pdgId'), ('java.util.List<Variant>', 'variant')],
        'Variant': [('String','id'), ('String','lemma'), ('String','prystauki'), ('String','zmienyFanietyki'), ('java.util.List<Form>','form')],
        'Form': [('String','value')],
    }
    for name, fields in classes.items():
        source = f'package org.alex73.grammardb.structures; public class {name} {{\n'
        for typ, field in fields:
            default = ' = new java.util.ArrayList<>()' if typ.startswith('java.util.List') else ''
            cap = field[0].upper() + field[1:]
            source += f'private {typ} {field}{default}; public {typ} get{cap}() {{return {field};}} public void set{cap}({typ} v) {{{field}=v;}}\n'
        write(f'org/alex73/grammardb/structures/{name}.java', source + '}')
    for name, package in [('BrowserG2P', 'org/belvoice/browser'), ('GrammarFinder','org/alex73/grammardb')]:
        write(f'{package}/{name}.java', (BUILD / f'{name}.java').read_text())

    resources = {'/' + str(p.relative_to(upstream / 'resources')): p.read_text()
                 for p in (upstream / 'resources').rglob('*') if p.is_file()}
    (OUTPUT / 'resources.json').write_text(json.dumps(resources, ensure_ascii=False))
    jar = pooch.retrieve(
        url='https://github.com/Belarus/BelG2P/releases/download/1.0.0/linguistics.BelG2P-1.0.0-jar-with-dependencies.jar', known_hash=None)
    if not (OUTPUT / 'grammar.json.gz').exists():
        subprocess.run(['javac', '-cp', jar, '-d', str(BUILD / 'export-classes'), str(BUILD / 'ExportGrammar.java')], check=True)
        subprocess.run(['java', '-Xmx2g', '-cp', os.pathsep.join([str(BUILD / 'export-classes'), jar]), 'ExportGrammar', str(OUTPUT / 'grammar.json.gz')], check=True)
    subprocess.run([args.maven, '-B', '-q', 'package'], cwd=BUILD, check=True)
    (OUTPUT / 'build-info.json').write_text(json.dumps({
        'belg2p': '1.0.0', 'teavm': '0.16.0', 'grammardb_reader': '1.5.0',
        'jar_sha256': hashlib.sha256(Path(jar).read_bytes()).hexdigest(),
        'source_sha256': hashlib.sha256((cache / 'belg2p.tar.gz').read_bytes()).hexdigest(),
        'adaptations': ['static dispatch instead of reflection', 'browser-backed resource and GrammarFinder storage',
                        'minimal morphology DTOs instead of JAXB', 'UTF-8 key=value reader for sound tables',
                        'RuntimeException instead of ExceptionInInitializerError', 'natural sort for debug-only case names',
                        'expose the unchanged pure compareWord matcher for optional ML OOV lookup'],
    }, indent=2))
    # Ship the exact adapted source and upstream license for inspection/relinking.
    with tarfile.open(OUTPUT / 'adapted-source.tar.gz', 'w:gz') as archive:
        archive.add(generated, arcname='generated')
        archive.add(BUILD / 'pom.xml', arcname='pom.xml')
    shutil.copyfile(cache / 'BelG2P-1.0.0/LICENSE.md', OUTPUT / 'LICENSE-BelG2P.md')


def adapt_dispatch(source, upstream):
    """Generate direct calls from the actual @ProcessCase declarations."""
    constructors, cases = [], []
    for f in sorted((upstream / 'java/org/alex73/fanetyka/processes').glob('*.java')):
        found = re.findall(r'@ProcessCase\(name\s*=\s*"([^"]+)"[^\n]*\)\s+public boolean (\w+)\(([^)]*)\)', f.read_text())
        if not found:
            continue
        constructors.append(f'case "{f.stem}": processor = new org.alex73.fanetyka.processes.{f.stem}(); break;')
        for case, method, params in found:
            arguments, index = [], 0
            for param in params.split(','):
                typ = param.strip().split()[0]
                if typ == 'Huk':
                    arguments.append(f'(context.currentPosition+{index}<context.huki.size() ? context.huki.get(context.currentPosition+{index}) : null)')
                    index += 1
                elif typ == 'ProcessContext':
                    arguments.append('context')
                else:
                    raise RuntimeError(f'Unknown process parameter {param}')
            cases.append(f'case "{f.stem}/{case}": return ((org.alex73.fanetyka.processes.{f.stem})processor).{method}({",".join(arguments)});')
    source = source.replace('private final Map<String, Method> methods = new TreeMap<>();', '')
    begin = source.index('        processor = process.getDeclaredConstructor().newInstance();')
    end = source.index('\n    @Override', begin)
    source = source[:begin] + '''        String processName = process.getSimpleName();
        config = new TsvConfig(processName, new ByteArrayInputStream(configs.get(processName)));
        switch(processName) {\n''' + '\n'.join(constructors) + '''
        default: throw new IllegalArgumentException(processName);
        }
    }
    private boolean invoke(String caseName, ProcessContext context) {
        switch(processType.getSimpleName()+"/"+caseName) {
''' + '\n'.join(cases) + '''
        default: throw new IllegalArgumentException(caseName);
        }
    }
''' + source[end:]
    source = source.replace('            Method m = methods.get(caseName);', '')
    begin = source.index('                // збіраем параметры')
    end = source.index('\n            }\n        }\n    }', begin)
    source = source[:begin] + '                invoke(caseName, context);' + source[end:]
    return source


if __name__ == '__main__':
    main()
