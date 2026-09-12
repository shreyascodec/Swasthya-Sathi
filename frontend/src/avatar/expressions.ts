// Clinic-facing expression / gesture cues for the Brenin avatar.
// English + Hindi (Devanagari) — intake questions are usually Hindi.

export const EXPRESSION_KEYWORDS: Record<string, RegExp> = {
  happy: /\b(great|fantastic|wonderful|amazing|excellent|awesome|love|joy|happy|glad|congrats|perfect|brilliant|yay|nice|good news)\b|बहुत अच्छा|बढ़िया|शाबाश|खुश|बधाई|शुभ/i,
  sad: /\b(sorry|unfortunately|sad|miss|regret|apolog|lost|fail|disappoint|bad news|oh no|sadly)\b|माफ़|दुख|अफसोस|खेद|बुरी खबर|दुखद/i,
  surprised: /\b(wow|whoa|incredible|unbelievable|no way|really\?|seriously\?|can't believe|astonishing|what\?|omg)\b|अरे वाह|क्या बात|हे भगवान|सच में/i,
  angry: /\b(unacceptable|ridiculous|outrageous|frustrated|furious|angry|wrong|absurd|nonsense)\b|गलत|नाराज|गुस्सा/i,
  thinking: /\b(hmm|let me think|consider|perhaps|maybe|possibly|interesting|curious|wonder|not sure)\b|सोच|शायद|संभव|दिलचस्प|पता नहीं|कृपया बता/i,
  laugh: /\b(haha|hehe|lol|hilarious|funny|laugh|joke|so funny)\b|हंसी|मजाक/i,
  excited: /\b(can't wait|so excited|thrilled|pumped|stoked|let's go|finally|here we go)\b|उत्साहित|चलो|आखिरकार/i,
};

/** Soft clinical defaults when a question is being asked (closed bank). */
export const CLINIC_QUESTION_EXPR = "thinking";

export function detectExpression(text: string, fallback = "neutral"): string {
  if (!text?.trim()) return fallback;
  for (const [expr, pattern] of Object.entries(EXPRESSION_KEYWORDS)) {
    if (pattern.test(text)) return expr;
  }
  return fallback;
}

// Head gestures (AvatarModel one-shots)
export const NOD_KEYWORDS =
  /\b(yes|sure|absolutely|exactly|correct|right|agree|definitely|of course|certainly|indeed|great|perfect)\b|हाँ|हां|जी|बिल्कुल|सही|ठीक|सहमत/i;

export const SHAKE_KEYWORDS =
  /\b(no|never|not|don't|can't|won't|disagree|incorrect|wrong|nope|negative)\b|नहीं|मत|गलत|असहमत/i;
