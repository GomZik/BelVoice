import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import java.util.zip.GZIPOutputStream;
import org.alex73.grammardb.*;
import org.alex73.grammardb.structures.*;

/** Build-time only: preserve the real GrammarFinder buckets and morphology. */
public class ExportGrammar {
    static Writer out;
    static void str(String s) throws IOException {
        if (s == null) { out.write("null"); return; }
        out.write('"');
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            if (c == '"' || c == '\\') { out.write('\\'); out.write(c); }
            else if (c < 32) out.write(String.format("\\u%04x", (int)c));
            else out.write(c);
        }
        out.write('"');
    }
    public static void main(String[] args) throws Exception {
        GrammarDB2 db = GrammarDB2.initializeFromJar();
        GrammarFinder finder = new GrammarFinder(db);
        List<Paradigm> all = db.getAllParadigms();
        IdentityHashMap<Paradigm, Integer> ids = new IdentityHashMap<>();
        for (int i = 0; i < all.size(); i++) ids.put(all.get(i), i);
        var tf = GrammarFinder.class.getDeclaredField("table"); tf.setAccessible(true);
        Paradigm[][] table = (Paradigm[][]) tf.get(finder);
        var ff = GrammarFinder.class.getDeclaredField("fan"); ff.setAccessible(true);
        @SuppressWarnings("unchecked") Map<String,String> fan = (Map<String,String>) ff.get(finder);
        try (Writer w = new BufferedWriter(new OutputStreamWriter(
                new GZIPOutputStream(Files.newOutputStream(Path.of(args[0]))), StandardCharsets.UTF_8))) {
            out = w; out.write("{\"paradigms\":[");
            boolean firstP = true;
            for (Paradigm p : all) {
                if (!firstP) out.write(','); firstP = false;
                out.write('['); out.write(Integer.toString(p.getPdgId())); out.write(",[");
                boolean firstV = true;
                for (Variant v : p.getVariant()) {
                    if (!firstV) out.write(','); firstV = false;
                    out.write('['); str(v.getId()); out.write(','); str(v.getLemma());
                    out.write(','); str(v.getPrystauki()); out.write(','); str(v.getZmienyFanietyki());
                    out.write(",["); boolean firstF = true;
                    for (Form f : v.getForm()) {
                        if (!firstF) out.write(','); firstF = false; str(f.getValue());
                    }
                    out.write("]]");
                }
                out.write("]]");
            }
            out.write("],\"table\":[");
            for (int i = 0; i < table.length; i++) {
                if (i > 0) out.write(',');
                out.write('[');
                if (table[i] != null) for (int j = 0; j < table[i].length; j++) {
                    if (j > 0) out.write(','); out.write(Integer.toString(ids.get(table[i][j])));
                }
                out.write(']');
            }
            out.write("],\"fan\":{"); boolean first = true;
            for (var entry : new TreeMap<>(fan).entrySet()) {
                if (!first) out.write(','); first = false;
                str(entry.getKey()); out.write(':'); str(entry.getValue());
            }
            out.write("}}");
        }
        System.out.println("Exported " + all.size() + " paradigms, " + fan.size() + " phonetic overrides");
    }
}
