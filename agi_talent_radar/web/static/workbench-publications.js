window.PublicationCards = (() => {
  const SUBMISSION_PATTERN = /在投|投稿中|审稿中|under\s+review|submitted|submission|manuscript|preprint|arxiv/i;

  function analyze(publications, candidateName) {
    const parsed = (Array.isArray(publications) ? publications : [])
      .map((publication) => parsePublication(String(publication || "")))
      .filter((publication) => publication.raw);
    const candidateKeys = inferCandidateKeys(parsed, candidateName);
    return parsed.map((publication) => markCandidate(publication, candidateKeys));
  }

  function parsePublication(raw) {
    const text = raw.trim().replace(/^[•·\-]\s*/, "");
    const labeled = parseLabeledPublication(text);
    if (labeled) return labeled;

    const quoteStart = text.search(/["“]/);
    const remaining = quoteStart >= 0 ? text.slice(quoteStart + 1) : "";
    const relativeQuoteEnd = remaining.search(/["”]/);
    const quoteEnd = relativeQuoteEnd >= 0 ? quoteStart + 1 + relativeQuoteEnd : -1;
    const authorsText = quoteStart >= 0 ? text.slice(0, quoteStart).replace(/[.\s]+$/, "") : "";
    const title = quoteStart >= 0 && quoteEnd > quoteStart
      ? text.slice(quoteStart + 1, quoteEnd).trim()
      : text;
    const venue = quoteEnd >= 0 ? text.slice(quoteEnd + 1).replace(/^[.\s]+/, "").trim() : "";
    return {
      raw: text,
      title,
      authors: splitAuthors(authorsText),
      venue,
      status: publicationStatus(text),
    };
  }

  function parseLabeledPublication(text) {
    const authorsMatch = text.match(/(?:作者|authors?)\s*[:：]\s*([^;；]+)/i);
    const titleMatch = text.match(/(?:题目|title)\s*[:：]\s*([^;；]+)/i);
    if (!authorsMatch && !titleMatch) return null;
    const venueMatch = text.match(/(?:会议\/期刊|会议|期刊|venue|conference|journal)\s*[:：]\s*([^;；]+)/i);
    const yearMatch = text.match(/(?:年份|year)\s*[:：]\s*([^;；]+)/i);
    return {
      raw: text,
      title: titleMatch?.[1]?.trim() || text,
      authors: splitAuthors(authorsMatch?.[1] || ""),
      venue: [venueMatch?.[1], yearMatch?.[1]].filter(Boolean).join(" · "),
      status: publicationStatus(text),
    };
  }

  function splitAuthors(value) {
    return value
      .split(/,|，|、/)
      .map((author) => author.trim())
      .filter(Boolean);
  }

  function inferCandidateKeys(publications, candidateName) {
    const exactKey = normalizeAuthor(candidateName);
    const counts = new Map();
    publications.forEach((publication) => {
      const seen = new Set();
      publication.authors.forEach((author) => {
        const key = normalizeAuthor(author);
        if (!key || seen.has(key)) return;
        seen.add(key);
        counts.set(key, (counts.get(key) || 0) + 1);
      });
    });

    const keys = new Set();
    if (exactKey && counts.has(exactKey)) keys.add(exactKey);
    if (publications.length >= 2 && counts.size) {
      const maxCount = Math.max(...counts.values());
      const threshold = Math.max(2, Math.ceil(publications.length * 0.6));
      if (maxCount >= threshold) {
        const mostFrequent = [...counts.entries()].filter(([, count]) => count === maxCount);
        if (mostFrequent.length === 1) keys.add(mostFrequent[0][0]);
      }
    }
    return keys;
  }

  function markCandidate(publication, candidateKeys) {
    const authors = publication.authors.map((display) => ({
      display,
      isCandidate: candidateKeys.has(normalizeAuthor(display)),
    }));
    const candidateIndex = authors.findIndex((author) => author.isCandidate);
    const candidateAuthor = candidateIndex >= 0 ? authors[candidateIndex].display : "";
    const coFirst = /[*†‡]/.test(candidateAuthor);
    return {
      ...publication,
      authors,
      positionLabel: candidateIndex >= 0
        ? `第 ${candidateIndex + 1} 作者${coFirst ? " · 共同一作" : ""}`
        : "",
    };
  }

  function publicationStatus(text) {
    return SUBMISSION_PATTERN.test(text)
      ? { key: "submitted", label: "在投" }
      : { key: "published", label: "已发表" };
  }

  function normalizeAuthor(value) {
    return String(value || "")
      .toLowerCase()
      .replace(/[*†‡]/g, "")
      .replace(/[^a-z0-9\u3400-\u9fff]+/g, " ")
      .trim()
      .replace(/\s+/g, " ");
  }

  return { analyze, parsePublication };
})();
