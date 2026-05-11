public class Hit {
    private final String sentenceId;
    private final String synonymId;
    private final String matchedText;
    private final int startPos;
    private final int hitLength;
    private final String synonym;
    private final String prefix;
    private final String suffix;

    public Hit(String sentenceId,
               String synonymId,
               String matchedText,
               int startPos,
               int hitLength,
               String synonym,
               String prefix,
               String suffix) {
        this.sentenceId = sentenceId;
        this.synonymId = synonymId;
        this.matchedText = matchedText;
        this.startPos = startPos;
        this.hitLength = hitLength;
        this.synonym = synonym;
        this.prefix = prefix;
        this.suffix = suffix;
    }

    public int getHitLength() {
        return hitLength;
    }

    public int getStartPos() {
        return startPos;
    }

    public String getMatchedText() {
        return matchedText;
    }

    public String getPrefix() {
        return prefix;
    }

    public String getSentenceId() {
        return sentenceId;
    }

    public String getSuffix() {
        return suffix;
    }

    public String getSynonym() {
        return synonym;
    }

    public String getSynonymId() {
        return synonymId;
    }

}
