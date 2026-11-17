import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import java.util.zip.GZIPOutputStream;

/** Uses BelVoice's original ambiguity/accepted-form selection, not a new heuristic. */
public class ExportStressDictionary {
    static void string(Writer out, String value) throws IOException {
        out.write('"');
        for (char c : value.toCharArray()) {
            if (c == '"' || c == '\\') { out.write('\\'); out.write(c); }
            else if (c < 32) out.write(String.format("\\u%04x", (int)c));
            else out.write(c);
        }
        out.write('"');
    }
    public static void main(String[] args) throws Exception {
        Map<String,String> entries = new TreeMap<>(new GrammarDBStressReader("").getNoHomographs());
        try (Writer out = new BufferedWriter(new OutputStreamWriter(
                new GZIPOutputStream(Files.newOutputStream(Path.of(args[0]))), StandardCharsets.UTF_8))) {
            out.write('{');
            boolean first = true;
            for (var entry : entries.entrySet()) {
                if (!first) out.write(','); first = false;
                string(out, entry.getKey()); out.write(':'); string(out, entry.getValue());
            }
            out.write('}');
        }
        System.out.println("Exported " + entries.size() + " unambiguous stress entries");
    }
}
