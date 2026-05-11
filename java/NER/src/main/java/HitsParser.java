import java.io.BufferedReader;
import java.io.FileReader;
import java.io.IOException;

public class HitsParser {
    public static void readHits(String path) throws IOException {
        BufferedReader reader = new BufferedReader(new FileReader(path));
        String line = reader.readLine();

        while (line != null) {
            String[] parts = line.split("\t");
            String sentId = parts[0];
            String synId = parts[1];
            String matchedText = parts[2];
            int startPos = Integer.parseInt(parts[3]);
            int hitLength = Integer.parseInt(parts[4]);
            String synonym = parts[5];
            String prefix = parts[6];
            String suffix = parts[7];
            Hit hit = new Hit(sentId, synId, matchedText, startPos, hitLength, synonym, prefix, suffix);

            line = reader.readLine();
        }
    }
}
