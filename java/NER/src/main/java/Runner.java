import java.io.IOException;

public class Runner {
    public static void main(String[] args) {
        HitsAnalyzer analyzer = new HitsAnalyzer();
        String sentencePath = "/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/data/corpus/original/everything.sent";
        System.out.println("Reading sentences...");
        try {
            analyzer.analyzeHits(null, sentencePath, null, null);
        } catch (IOException e) {
            System.err.print(e);
        }
    }
}
