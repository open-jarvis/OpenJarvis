//! Storage utilities — text chunking and document ingestion.

/// Split text into overlapping chunks for indexing.
pub fn chunk_text(text: &str, chunk_size: usize, overlap: usize) -> Vec<String> {
    let words: Vec<&str> = text.split_whitespace().collect();
    if words.is_empty() {
        return vec![];
    }
    if words.len() <= chunk_size {
        return vec![words.join(" ")];
    }

    let mut chunks = Vec::new();
    let step = if chunk_size > overlap {
        chunk_size - overlap
    } else {
        1
    };
    let mut start = 0;

    while start < words.len() {
        let end = (start + chunk_size).min(words.len());
        chunks.push(words[start..end].join(" "));
        start += step;
        if end == words.len() {
            break;
        }
    }

    chunks
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_chunk_text() {
        let text = "one two three four five six seven eight nine ten";
        let chunks = chunk_text(text, 4, 1);
        assert!(chunks.len() >= 3);
        assert_eq!(chunks[0], "one two three four");
    }

    #[test]
    fn test_chunk_text_short() {
        let text = "hello world";
        let chunks = chunk_text(text, 10, 2);
        assert_eq!(chunks.len(), 1);
    }

    #[test]
    fn test_chunk_text_empty() {
        let chunks = chunk_text("", 10, 2);
        assert!(chunks.is_empty());
    }
}
