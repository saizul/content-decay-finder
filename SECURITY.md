# Security policy

## Supported versions

Security fixes are made for the latest release. Please upgrade before reporting.

| Version | Supported |
| ------- | --------- |
| 0.1.x   | yes       |

## Reporting a vulnerability

Please do not open a public issue for a security problem. Use GitHub's private
vulnerability reporting instead: open the **Security** tab of
https://github.com/saizul/content-decay-finder and choose **Report a
vulnerability**.

Include what you found, how to reproduce it and what an attacker could do with
it. You should get an answer within a week. Once a fix is released you will be
credited in the changelog unless you prefer otherwise.

Never include service account keys, access tokens or real Search Console data
in a report. Replace domains with `example.com` and use made-up numbers.

## Scope

In scope:

- leaking credentials: keys or tokens in logs, reports, error messages or files
  with loose permissions
- injection through untrusted data in reports: HTML/SVG (cross-site scripting),
  Markdown, spreadsheet formulas in CSV files
- parsing of untrusted CSV files and API answers (crashes, excessive memory or
  CPU use)
- the token request and API client (scopes, TLS, handling of error answers)

Out of scope: the accuracy of Search Console data itself, and the security of
the Google Cloud project that owns the service account.
