# IsItTrue — Privacy Policy

_Last updated: 2026-08-27_

IsItTrue (the web app, and the "IsItTrue" browser
extension) checks text or images for false claims. This page explains
what happens to what you submit.

## What we collect

When you check something — by pasting/attaching it in the web app, or by
right-clicking selected text or an image with the extension — we send
that text and/or image to our backend server, which sends it to Google's
Gemini API to be analyzed. We do not require or collect your name, email
address, or any account information; there is no login.

## What we store, and for how long

- **Checked content**: cached by a content hash (not by who submitted
  it) for 30 days, so an identical forward doesn't have to be re-checked
  from scratch. This cache has no link back to any individual — it's keyed
  purely by the content itself.
- **A single anonymous cookie** (or, before that cookie is set, your IP
  address for that one request) is used only to apply a daily limit on
  how many free checks one browser can run — this is a fraud/cost control,
  not tracking, and isn't linked to any other data about you.
- **Basic operational logs** (request size, verdict counts, timestamps)
  for debugging and keeping the service within budget. We do not log the
  full text or images you submit.

## Third parties

Submitted text/images are sent to **Google's Gemini API** for analysis,
subject to [Google's own privacy terms](https://policies.google.com/privacy).
We don't sell or share what you submit with anyone else, and we don't use
it for advertising.

## The browser extension specifically

The extension only acts when you explicitly right-click selected text or
an image and choose "Check this text/image with IsItTrue" — it
does not read, monitor, or transmit anything on any page otherwise. The
broad site-access permission it requests exists so that action can work
on whatever page you're using it on (needed to fetch the image you
right-clicked, and to call our backend) — not to observe your browsing.

## Changes

If this policy changes, the update will be posted here with a new "last
updated" date.

## Contact

Questions about this policy: <your-contact-email-here>
