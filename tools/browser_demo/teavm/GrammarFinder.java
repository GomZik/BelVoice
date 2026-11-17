package org.alex73.grammardb;

import org.alex73.grammardb.structures.*;
import org.teavm.jso.JSBody;

/** Browser storage adapter. The exported buckets/data come from the real JAR. */
public class GrammarFinder {
    private final char[] letters = new char[0x2020];
    public GrammarFinder() {
        for (char c=0; c<letters.length; c++)
            if (Character.isLetterOrDigit(c)) letters[c] = Character.toLowerCase(c);
        String from = "ґўйёеяюь", to = "гуіоэау\0";
        for (int i=0; i<from.length(); i++) {
            letters[from.charAt(i)] = to.charAt(i);
            letters[Character.toUpperCase(from.charAt(i))] = to.charAt(i);
        }
    }
    public Paradigm[] getParadigms(String word) {
        int hash = 0;
        for (int i=0; i<word.length(); i++) {
            char c=word.charAt(i); c = c<letters.length ? letters[c] : 0;
            if (c>0) hash = 31*hash+c;
        }
        int bucket = Math.abs(hash) % (256*1024);
        int count = count(bucket);
        Paradigm[] result = new Paradigm[count];
        for (int i=0; i<count; i++) {
            int id = paradigm(bucket,i);
            Paradigm p = new Paradigm(); p.setPdgId(paradigmId(id));
            for (int v=0; v<variants(id); v++) {
                Variant variant = new Variant();
                variant.setId(field(id,v,0)); variant.setLemma(field(id,v,1));
                variant.setPrystauki(field(id,v,2)); variant.setZmienyFanietyki(field(id,v,3));
                for (int f=0; f<forms(id,v); f++) {
                    Form form = new Form(); form.setValue(form(id,v,f)); variant.getForm().add(form);
                }
                p.getVariant().add(variant);
            }
            result[i]=p;
        }
        return result;
    }
    public String getFan(String word) { return fan(StressUtils.unstress(word).toLowerCase()); }
    @JSBody(params={"bucket"},script="return globalThis.belg2pGrammar.table[bucket].length;")
    private static native int count(int bucket);
    @JSBody(params={"bucket","i"},script="return globalThis.belg2pGrammar.table[bucket][i];")
    private static native int paradigm(int bucket,int i);
    @JSBody(params={"id"},script="return globalThis.belg2pGrammar.paradigms[id][0];")
    private static native int paradigmId(int id);
    @JSBody(params={"id"},script="return globalThis.belg2pGrammar.paradigms[id][1].length;")
    private static native int variants(int id);
    @JSBody(params={"id","v","f"},script="return globalThis.belg2pGrammar.paradigms[id][1][v][f];")
    private static native String field(int id,int v,int f);
    @JSBody(params={"id","v"},script="return globalThis.belg2pGrammar.paradigms[id][1][v][4].length;")
    private static native int forms(int id,int v);
    @JSBody(params={"id","v","f"},script="return globalThis.belg2pGrammar.paradigms[id][1][v][4][f];")
    private static native String form(int id,int v,int f);
    @JSBody(params={"word"},script="return globalThis.belg2pGrammar.fan[word] || null;")
    private static native String fan(String word);
}
