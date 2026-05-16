# Triage Graph: akshettrj/watgbridge

**Date:** 2026-05-11  
**Stars:** 267  
**Issues:** 22 open  
**Language:** Go  
**Maintainer:** akshettrj (91% of commits, 332/365)

## Repo Context

WhatsApp-Telegram bridge using whatsmeow and gotgbot. Solo maintainer, 10 external PRs merged historically. 1 open PR (#68) from external contributor.

## Triage Sessions

### Session 1: 2026-05-11 (Initial scan, fix for #46)

**Outcome:** 1 branch created (`fix-disappearing-messages-46`)

Fixed issue #46 - the only actionable bug in the backlog. Ephemeral message timer was partially implemented (database + main flow) but two edge case handlers were missing the check.

### Session 2: 2026-05-11 (Full scan for additional issues)

**Outcome:** 0 new branches created

**Finding:** No additional actionable bugs in the backlog. All 21 remaining issues are:
- **17 feature requests**: Complex, require WhatsApp API knowledge or major refactoring
- **2 user errors**: Database state issues or device-specific problems  
- **1 resolved in comments**: Compiler warning (not a bug)
- **1 needs investigation**: WhatsApp API debugging required

## Issue Analysis

### #46: Fix sending messages to groups with Disappearing timer (FIXED)

**Status:** Fixed in branch `fix-disappearing-messages-46`  
**Type:** Bug - incomplete feature implementation  
**Maintainer-filed:** Yes (akshettrj)

**Root Cause:** Ephemeral settings infrastructure existed (database schema `ChatEphemeralSettings`, tracking in handlers, application in main telegram.go message flow at line 247-276), but two code paths bypassed it:

1. `WaTagAll` function (@all/@everyone handler) in `utils/whatsapp.go:197`
2. `.id` command in `whatsapp/handlers.go:125`

Both sent `ExtendedTextMessage` without checking `database.GetEphemeralSettings()` or setting `ContextInfo.Expiration`.

**Fix:** Added ephemeral settings check to both code paths. Pattern:
```go
contextInfo := &waE2E.ContextInfo{...}
isEphemeral, ephemeralTimer, _, err := database.GetEphemeralSettings(chatId)
if err == nil && isEphemeral {
    contextInfo.Expiration = &ephemeralTimer
}
```

**Files Changed:** 3 (whatsapp/handlers.go, utils/whatsapp.go, database/helpers_test.go)  
**Review:** Gemini approved logic and implementation. Noted test uses `t.Skipf` which is acceptable for local dev but not ideal for CI/CD (would silently pass if DB unavailable).

**Evidence for H2 (Incomplete feature > missing feature):** SUPPORTED  
Maintainer filed the issue with implementation guidance ("Disappear timer will have to be stored locally, and then while sending the message, will have to add the ephemeral setting"). Storage WAS implemented, sending was PARTIALLY implemented. Classic incomplete rollout.

---

## Full Issue Survey (All 22 Open Issues)

### #82: group message (2026-04-21, no comments)
**Type:** Unclear/vague  
**Verdict:** Skip - "do you have a sample to send a message to a group with image?" is a usage question, not a bug or feature request

### #76: Topic Deleted (2025-05-11, no comments)
**Type:** User error / database cleanup issue  
**Body:** "topic Deleted by mistake and unable to put new topic as it says 'A topic already exists in database for the given WhatsApp chat. Aborting...'"  
**Verdict:** Skip - database state issue, needs manual database repair, not a code bug

### #73: Audio notes not playing (2025-02-07, no comments)
**Type:** Feature request or device-specific issue  
**Body:** "audio notes are not playing on whatsapp. one more things audio notes should be displayed on WhatsApp as voice note rather than mp3 file"  
**Verdict:** Skip - needs device testing to reproduce, no repro steps, unclear if bug or feature gap

### #71: Download Previous Data from WhatsApp (2025-01-12, no comments)
**Type:** Feature request  
**Body:** "feature that allows downloading previous messages from WhatsApp"  
**Verdict:** Skip - major feature, no prior history, requires WhatsApp API investigation

### #69: Multi-Language Support (2025-01-10, no comments)
**Type:** Feature request  
**Body:** "add multi-language support to the Telegram side...users to create language-specific files (e.g., `en.lang`, `fr.lang`)"  
**Verdict:** Skip - i18n infrastructure needed, no existing l10n system

### #61: /send will create a new thread (2024-07-16, maintainer acknowledged, 4 comments)
**Type:** Feature request  
**Body:** "if we use the /send command it won't create a topic unless someone replied to the message. So I was thinking if we send 'hello world' with the /send it will directly open a topic"  
**Maintainer response:** "will take some time (few weeks) am a bit busy. You are welcome to make a PR if you are familiar with Golang"  
**Verdict:** Skip for first PR - maintainer acknowledged as complex, no clear spec for auto-thread creation logic

### #57: Button for adding to group (2024-05-11, maintainer-filed)
**Type:** Feature request  
**Body:** "Use the API to send a button through the bot for selecting/creating the target chat on Telegram during initial setup"  
**Verdict:** Skip - UX feature, no implementation path

### #56: Link thread instead of WhatsApp link (2024-04-02, maintainer-filed)
**Type:** Feature request  
**Body:** Empty  
**Verdict:** Skip - no description, enhancement not a bug

### #55: One time voice notes not working (2024-03-29, maintainer-filed)
**Type:** Feature request or bug  
**Body:** Empty  
**Verdict:** Skip - no description, needs WhatsApp API investigation

### #54: Sync pinned messages (2024-03-29, maintainer-filed)
**Type:** Feature request  
**Body:** Empty  
**Verdict:** Skip - new feature (sync pinned message state between WhatsApp and Telegram)

### #53: Linker warning when compiling (2024-03-14, RESOLVED in comments, 6 comments)
**Type:** Not a bug  
**Maintainer response:** "The rlottie one is just warning. You can ignore that. The ldd one also looks like a warning. Is any binary file named watgbridge getting generated?"  
**User:** "Yes, a binary named `watgbridge` was generated with approximately 35.4MB"  
**Verdict:** Skip - resolved, warnings are ignorable, binary was generated successfully

### #52: Add status update (2024-03-08, maintainer engaged, 3 comments)
**Type:** Feature request  
**Body:** "the ability to post a status update directly from TG"  
**Maintainer response:** "status updates are already supported" (misunderstood initially), then "Will see if its possible"  
**Verdict:** Skip - feature request, maintainer investigating feasibility

### #51: wa markdown <=> tg entities (2024-02-23, maintainer-filed)
**Type:** Feature request  
**Body:** Empty  
**Verdict:** Skip - format conversion feature, no spec

### #50: Forward React from WhatsApp (2024-02-12, 4 comments)
**Type:** Feature request  
**Body:** "Able to send message or react to telegram when receiver react to messages on WhatsApp"  
**Maintainer response:** "the problem is that the there are restrictions on what emojis can the bot react with (I think there are only 32 available emojis at the moment). So, I guess for those emojis, we can directly react to the respective messages, and otherwise we can make it configurable whether to send reactions as separate message or just ignore them"  
**Verdict:** Skip for first PR - requires understanding Telegram's 32-emoji restriction and implementing emoji mapping/config

### #47: Information about WhatsApp Chat on Telegram (2024-01-14)
**Type:** Feature request  
**Body:** "Request to sendPhoto on Telegram side when a new chat is created from WhatsApp side after createForumTopic api is called"  
**Verdict:** Skip - new feature (photo on forum topic creation)

### #45: URL previews (2023-10-23)
**Type:** Feature request  
**Body:** "messages containing an URL sent through `watgbridge` do not have the preview generated from HTML tags `<meta property=\"og:image\">`"  
**Verdict:** Skip - OG meta tag parsing feature, significant implementation effort

### #32: Bot messages with buttons not forwarded (2023-07-25, maintainer acknowledged, 3 comments)
**Type:** Feature request  
**Body:** "WA bot messages with response buttons do not get forwarded to telegram"  
**Maintainer response:** "Ah yes, the messages with buttons are not handled yet"  
**Verdict:** Skip - button message handling not implemented yet, feature gap

### #30: Group invite link possibly broken (2023-07-10, maintainer investigating, 1 comment)
**Type:** Bug (possibly)  
**Body:** "Failed to join: info query returned status 400: bad-request"  
**Maintainer response:** "It might be due to new feature of requiring approval from admin. I will test around"  
**Verdict:** Skip - needs WhatsApp API debugging, server logs, unclear if code bug or API change

### #27: Handle edited message updates from WhatsApp (2023-05-31, maintainer-filed)
**Type:** Feature request  
**Body:** Empty  
**Verdict:** Skip - edit support not implemented

### #26: Edit messages from Telegram's side (2023-05-31, maintainer-filed)
**Type:** Feature request  
**Body:** Empty  
**Verdict:** Skip - edit support not implemented

---

## Issue Landscape Summary

Out of 22 open issues:
- **1 bug** (incomplete feature): #46 (FIXED in session 1)
- **17 feature requests**: #82, #71, #69, #61, #57, #56, #54, #52, #51, #50, #47, #45, #32, #27, #26
- **2 user errors / unclear**: #76 (database state), #73 (no repro)
- **1 resolved in comments**: #53
- **1 needs investigation**: #30 (WhatsApp API)

**Conclusion:** This repo is feature-driven, not bug-driven. The maintainer files issues for planned features. External contributors mostly request features. Issue #46 was the ONLY actionable bug in the entire backlog.

### Code Quality Scan

- **TODOs in codebase:** 2 found
  1. `utils/telegram.go:925`: "TODO: make this live" - in live location message handling (needs WhatsApp API testing)
  2. `whatsapp/handlers.go:1409`: "TODO : Check and handle group calls" - in call offer handler (needs group call API investigation)
- **Test coverage:** 0 test files exist
- **go vet:** No warnings
- **staticcheck/golangci-lint:** Not available locally

Both TODOs require device testing or WhatsApp API investigation, not mechanically verifiable fixes.

---

## Competing PRs

- #68: "Restrict bot commands to group and sudo users only" (opened 2025-01-10)
  - No overlap with #46 (different files/concerns)

---

## Hypothesis Updates

**H2 (Incomplete feature > missing feature):** SUPPORTED  
Issue #46 was an incomplete rollout of ephemeral message support. Storage layer and main message flow were implemented, but two edge case handlers were missed.

**H3 (Maintainer-filed issues have clearer acceptance criteria):** SUPPORTED  
#46 had explicit implementation guidance in the issue description. Compare to #82 (user-filed, vague) or #73 (user-filed, no repro steps).

**H5 (Cold repos need bug fixes first):** SUPPORTED  
This repo has 10 external PRs merged historically, but no recent external contribution activity (last external PR unknown). The only actionable bug (#46) was found and fixed. All other issues are features or vague reports.

**NEW: H7 (Feature-driven repos have no standing path via bugs):**  
Some repos (like watgbridge) file most issues as planned features, not bugs. The backlog is a roadmap, not a bug tracker. No low-hanging fruit exists for cold contribution via bug fixes. Standing must be earned via:
1. Smallest feature request with maintainer engagement
2. Code quality improvements (tests, linting, documentation)
3. Wait for bugs to be filed

---

## Next Steps

**For watgbridge:** No additional work until:
1. Branch `fix-disappearing-messages-46` is dripped and PR'd
2. New bugs are filed (subscribe to repo notifications)
3. Re-evaluate feature requests after earning standing via #46 merge

**For pipeline:** Add feature-driven repo detection to /triage:
- Ratio of feature-request labels to bug labels
- Ratio of maintainer-filed issues to external-filed issues
- Presence of "roadmap" or "planned" labels
- Age of oldest open bug

If detected, warn in triage graph and suggest alternative repos.
