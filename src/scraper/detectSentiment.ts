import Sentiment from "sentiment";
import type { Sentiment as SentimentLabel } from "@/models/Review";

const analyzer = new Sentiment();

/** Map review text + star rating to positive/neutral/negative. */
export function detectSentiment(
  reviewText: string,
  reviewRating: number
): SentimentLabel {
  if (reviewRating <= 2) return "negative";
  if (reviewRating >= 4) {
    const result = analyzer.analyze(reviewText);
    if (result.score > 1) return "positive";
    if (result.score < -1) return "negative";
    return "positive";
  }
  if (reviewRating === 3) return "neutral";

  const result = analyzer.analyze(reviewText);
  if (result.score > 2) return "positive";
  if (result.score < -2) return "negative";
  return "neutral";
}
