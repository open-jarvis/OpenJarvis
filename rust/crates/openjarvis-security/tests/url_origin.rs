//! Regression for RUSTSEC-2026-0592 in the shared native URL dependency.

#[test]
fn deeply_nested_blob_origins_do_not_recurse() {
    std::thread::Builder::new()
        .stack_size(2 * 1024 * 1024)
        .spawn(|| {
            let input = format!("{}https://example.com/", "blob:".repeat(10_000));
            let parsed = url::Url::parse(&input).unwrap();
            assert!(matches!(parsed.origin(), url::Origin::Opaque(_)));
        })
        .unwrap()
        .join()
        .unwrap();
}

#[test]
fn single_blob_http_origin_is_preserved() {
    let parsed = url::Url::parse("blob:https://example.com/recording").unwrap();
    assert_eq!(parsed.origin().ascii_serialization(), "https://example.com");
}
