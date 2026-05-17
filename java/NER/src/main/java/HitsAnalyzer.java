import java.io.*;
import java.util.HashMap;
import java.util.Iterator;

public class HitsAnalyzer {

    public void analyzeHits(String hitsPath, String sentencePath, String fileMapPath, String out) throws IOException{
//        Iterator<Hit> hits = getHitsIterator(hitsPath);
//        HashMap<String, Hit> sentenceIdToHit = new HashMap<>();
        HashMap<String, Sentence> sentences = readSentences(sentencePath);

//        BufferedWriter writer = new BufferedWriter(new FileWriter(out), 512) {};
//        StringBuilder sb = new StringBuilder();
//
//        while (hits.hasNext()) {
//            Hit hit = hits.next();
//            Hit storedHit = sentenceIdToHit.get(hit.sentenceId());
//            if (storedHit != null) {
//                sb.append(hit.synFile()).append(':').append(storedHit.synFile()).append('\t').append(sentences.get(hit.sentenceId())).append('\n');
//                writer.write(sb.toString());
//                sb.setLength(0);
//                continue;
//            }
//            sentenceIdToHit.put(hit.sentenceId(), hit);
//        }

    }

    private HashMap<String, Sentence> readSentences(String path) throws IOException {
        BufferedReader reader = new BufferedReader(new FileReader(path));
        String line = reader.readLine();
        HashMap<String, Sentence> out = new HashMap<>();
        int count = 0;
        while (line != null) {
            if (count % 10_000 == 0) System.out.println("Read: " + count);
            String[] parts = line.split("\t");
            if (parts.length != 2) throw new RuntimeException("Illegal sentence format. Expected 2 columns, found " + parts.length);
            String id = parts[0];
            String text = parts[1];
            Sentence sentence = new Sentence(id, text);

            out.put(id, sentence);
            line = reader.readLine();
            count++;
        }

        return out;
    }

    private Iterator<Hit> getHitsIterator(String path) throws IOException {
        return new Iterator<Hit>() {
            final BufferedReader reader = new BufferedReader(new FileReader(path));
            String line = reader.readLine();

            @Override
            public boolean hasNext() {
                return line != null;
            }

            @Override
            public Hit next() {
                String[] parts = line.split("\t");
                if (parts.length != 8) throw new RuntimeException("Illegal hits format. Expected 8 columns, found " + parts.length);
                String sentId = parts[0];
                String fileAndSynId = parts[1];
                String matchedText = parts[2];
                int startPos = Integer.parseInt(parts[3]);
                int hitLength = Integer.parseInt(parts[4]);
                String synonym = parts[5];
                String prefix = parts[6];
                String suffix = parts[7];
                
                String[] tmp = fileAndSynId.split(":");
                String synFile = tmp[0];
                String synId = tmp[1];
                
                Hit hit = new Hit(sentId, synFile, synId, matchedText, startPos, hitLength, synonym, prefix, suffix);

                try {
                    line = reader.readLine();
                } catch (IOException e) {
                    throw new RuntimeException(e);
                }
                return hit;
            }
        };
    }

    private HashMap<String, String> parseFileMap(String path) throws IOException {
        HashMap<String, String> numToName = new HashMap<>();
        BufferedReader reader = new BufferedReader(new FileReader(path));
        String line = reader.readLine();
        
        while(line != null) {
            String[] parts = line.split("\t");
            if (parts.length != 2) throw new RuntimeException("Illegal synfile.map format. Expected 2 columns, found " + parts.length);
            String fileName = parts[0];
            String fileNum = parts[1]; // Stored as String to avoid conversion overhead in the hits parser
            numToName.put(fileNum, fileName);
            line = reader.readLine();
        }
        return numToName;
    }
}
