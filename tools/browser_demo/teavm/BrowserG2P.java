package org.belvoice.browser;

import java.util.*;
import org.alex73.fanetyka.impl.*;
import org.alex73.fanetyka.impl.str.ToStringIPA2TTS;
import org.alex73.grammardb.GrammarFinder;
import org.alex73.fanetyka.utils.Amohrafy;
import org.teavm.jso.JSBody;
import org.teavm.jso.JSExport;

public class BrowserG2P {
    private static FanetykaConfig config;
    private static GrammarFinder finder;
    private static String lastWarning;
    public static void main(String[] args) {}

    @JSExport
    public static String phonemize(String phrase) throws Exception {
        lastWarning = null;
        ensureConfig();
        try {
            return convert(phrase);
        } catch (RuntimeException error) {
            String message = error.getMessage();
            if (message == null || !(message.startsWith("Небывае мяккі:") || message.startsWith("У з'яве '"))) throw error;
            boolean previous = Huk.SKIP_ERRORS;
            String result;
            try {
                Huk.SKIP_ERRORS = true;
                result = convert(phrase);
            } finally {
                Huk.SKIP_ERRORS = previous;
            }
            lastWarning = "BelG2P: набліжанае вымаўленне (" + message + ")";
            return result;
        }
    }

    @JSExport
    public static String getLastWarning() { return lastWarning; }

    private static void ensureConfig() throws Exception {
        if (config == null) {
            finder = new GrammarFinder();
            config = new FanetykaConfig(finder);
        }
    }

    /** Keep dictionary words out of the optional neural OOV stress fallback. */
    @JSExport
    public static boolean hasDictionaryWord(String input) throws Exception {
        ensureConfig();
        StringBuilder normalized = new StringBuilder();
        for (int i=0; i<input.length(); i++) {
            char c=input.charAt(i);
            if (WordInitialConverter.usie_apostrafy.indexOf(c)>=0) c='\u02bc';
            if (WordInitialConverter.usie_naciski.indexOf(c)>=0) c='\u0301';
            normalized.append(c);
        }
        String word=normalized.toString();
        if (finder.getFan(word)!=null || Amohrafy.resolveAmohraf(word)!=null) return true;
        for (var paradigm:finder.getParadigms(word)) {
            for (var variant:paradigm.getVariant()) {
                for (var form:variant.getForm()) {
                    if (!form.getValue().isEmpty() && WordInitialConverter.compareWord(word,form.getValue())) return true;
                }
            }
        }
        return false;
    }

    private static String convert(String phrase) throws Exception {
        Fanetyka3 converter = new Fanetyka3(config);
        converter.calcFanetyka(new ArrayList<>(Arrays.asList(phrase.split("\\s+"))));
        return converter.toString(new ToStringIPA2TTS());
    }

    @JSBody(params = {"path"}, script = "return globalThis.belg2pResources[path];")
    public static native String resource(String path);
}
