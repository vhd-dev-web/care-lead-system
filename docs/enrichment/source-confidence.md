# Source Confidence

## Firm Identity

```text
0.95 official imprint or official register
0.90 Firecrawl Markdown from known same-domain imprint with legal identity
0.85 company footer/contact page
0.75 manually confirmed LinkedIn company page
0.65 Tavily research summary with matching source URLs
0.60 third-party directory with matching domain
0.40 search snippet or ambiguous title
```

## Decision Maker

```text
0.95 imprint explicitly names Geschaeftsfuehrer, Inhaber, or Vertreten durch
0.95 official register/manual confirmation
0.90 Firecrawl Markdown from known same-domain imprint with explicit role text
0.85 team/about page with explicit role
0.70 manually confirmed LinkedIn match
0.70 Tavily research summary with explicit role text
0.55 third-party directory only
0.30 inferred name or weak hint
```

Anything below `0.70` goes to manual review.

## Contact Data

```text
0.95 imprint or contact page mailto/tel
0.90 Firecrawl Markdown from known same-domain imprint/contact page
0.85 footer
0.75 structured data on same domain
0.60 third-party directory
0.40 snippet only
```

Personal email addresses must not be inferred.
