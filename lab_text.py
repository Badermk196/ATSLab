"""
Every text the app pages show (Admin page, User page, the queue, the settings), in one place, so they are easy to edit.
The report itself (the full report on the Admin page, its PDF, the client comparison) keeps its texts in dashboard.py:
REPORT_TEXT, CHECK_TEXT (messages for files that cannot be checked), CLIENT_TEXT and IMPROVE_TEXT.

Placeholders in braces ({n}, {name} ...) are filled in by the code; keep them when editing a text.
"""

APP_VERSION = "1.4"
BRAND = "1000Jobs"

# ---------------------------------------------------------------------------
# Admin page (the team)
# ---------------------------------------------------------------------------
# view key -> (sidebar label, Material icon)
NAV = {
    "check": ("Check a resume", ":material/upload_file:"),
    "history": ("History", ":material/history:"),
    "review": ("Needs review", ":material/warning:"),
    "settings": ("Settings", ":material/settings:"),
    "log": ("Activity log", ":material/list:"),
}

ADMIN_TEXT = {
    # sidebar
    "lab": "ATS LAB", "admin_badge": "★ ADMIN", "workspace": "WORKSPACE", "role": "Admin",
    "version": "ATS Lab v{version}", "sign_out": "Sign out",
    "signed_in": "Signed in as {name}",
    # sign in
    "login_title": "Admin sign in", "login_sub": "For the 1000Jobs team.",
    "name": "Name", "password": "Password", "sign_in": "Sign in",
    "wrong": "Wrong name or password.",
    "locked": "Too many wrong tries. Please wait a minute and try again.",
    "no_accounts": "No admin accounts are set up yet. Add them to the secrets (see DEPLOY.md).",
    # check a resume
    "check_title": "Check a resume",
    "check_sub": "Upload a PDF. Add a job description to see how well it matches the job.",
    "mode_job": "With job description", "mode_general": "General check",
    "resume": "Resume (PDF)", "drop": "Drop the PDF here or", "browse": "browse", "drop_hint": "One file · PDF only · up to 10 MB",
    "role_label": "Target role (job title)", "role_hint": "e.g. Brand Marketing Manager",
    "role_note": "Required with a job description",
    "jd_label": "Job description", "jd_hint": "Paste the full job description here",
    "jd_note": "Paste the full text for the best match",
    "general_note": "The resume is checked against the 1000Jobs resume standard: readability, content and structure.",
    "compare": "Compare with a previous resume · optional",
    "compare_sub": "Upload the older version to see what got better or worse.",
    "compare_client": "Client comparison report · the user's own resume vs the 1000Jobs resume",
    "compare_client_sub": "Both files are checked, then compared: what we fixed, and what is left in the user's own.",
    "previous": "Previous version (PDF)",
    # the client comparison report: the two files, clearly labelled, with a Swap button and a check before the report
    "pair_hint": "Put each file in its own slot. If they came the other way round, press Swap.",
    "slot_original": "1. The user's own original resume",
    "slot_original_hint": "The CV the user sent us",
    "slot_ours": "2. The 1000Jobs resume",
    "slot_ours_hint": "The resume our generator made",
    "swap": "Swap",
    "swap_help": "Read the two files the other way round",
    "swap_note": "Swapped: {ours} is read as the 1000Jobs resume and {original} as the user's own resume.",
    "roles_read": "Read as: {original} = the user's own resume · {ours} = the 1000Jobs resume",
    "roles_warn": "Careful: {file} is in the slot of the user's own resume, but it looks like a 1000Jobs resume "
                  "({marks}). The report would read it as the 1000Jobs resume. Press \"{swap}\" if the two files came "
                  "the other way round, or \"{confirm}\".",
    "roles_confirm": "Continue and build the report",
    "need_both": "For the client comparison report, upload both files: the user's own resume and the 1000Jobs resume.",
    "pair_wait": "Add both files to compare them.",
    "run": "Run check", "checking": "Checking the resume (a new job description is read by AI once, then saved)...",
    "new_check": "Check new resume", "new_check_short": "New check", "again": "Check again",
    "again_job": "Paste the job description to check this resume against the job.",
    "again_general": "Check this resume again without the job description.",
    "shows_title": "The report shows",
    "shows": ["A score from 0 to 100, split into readability, content and structure",
              "Every problem, why it matters and how to fix it",
              "Design issues: photo, colors, side panels, fonts",
              "Job match and missing keywords, when a job is added"],
    "recent": "Recent checks", "see_all": "See all", "no_recent": "No resume has been checked yet.",
    "saved": "Saved to the history.",
    "not_saved": "The check could not be saved to the history ({why}).",
    # history
    "history_title": "History",
    "history_sub": "Every resume checked by the team or on the user page. Click a row to open its report.",
    "stat_checks": "Checks", "stat_avg": "Average score", "stat_user": "From the user page",
    "stat_review": "Needs review",
    "search": "Search by candidate, file or job title", "all": "All",
    "f_job": "Job", "f_job_all": "With and without job", "f_job_with": "With job", "f_job_without": "Without job",
    "f_dates": "Dates", "f_by": "Checked by", "f_by_all": "Everyone", "f_by_user": "User page",
    "col_candidate": "Candidate", "col_date": "Date", "col_source": "Source", "col_job": "Job", "col_score": "Score",
    "col_review": "Review",
    "source_user": "User page", "general": "General check", "no_name": "(no name found)",
    "tag_review": "Needs review", "tag_reviewed": "Reviewed by {who}",
    "shown": "{n} of {total} checks", "prev_page": "Previous", "next_page": "Next", "page": "Page {n} of {pages}",
    "export": "Export CSV", "delete_selected": "Delete selected ({n})", "delete": "Delete record",
    "confirm_title": "Delete {n} record{s}?",
    "confirm_text": "This removes the report{s} and the resume file{s} for good. It cannot be undone.",
    "confirm_yes": "Delete for good", "cancel": "Cancel",
    "deleted": "{n} record{s} deleted.",
    # clearing a whole list (History, Needs review, Activity log)
    "clear_history": "Clear history",
    "clear_history_ask": "Remove every check, its report and its kept resume file? The Activity log and the settings stay.",
    "clear_history_yes": "Clear the history",
    "clear_history_done": "History cleared: {checks} checks and {files} resume files removed. The settings stay.",
    "clear_review": "Mark them all as reviewed",
    "clear_review_ask": "Mark all {n} flagged resumes as reviewed? They leave this list; their reports stay in History.",
    "clear_review_yes": "Mark them reviewed",
    "clear_review_done": "{n} resumes marked as reviewed by {who}.",
    "no_history": "No resume has been checked yet.",
    "no_match": "No checks match these filters.",
    "open": "Open report", "back": "Back to the list",
    "file_gone": "The resume file was deleted after {days} days (the report stays).",
    "file_none": "The resume file was not kept.",
    "download_file": "Download the resume file", "download_cmp": "Download comparison PDF",
    "contact": "Contact left on the user page: {name} <{email}>",
    # needs review
    "review_title": "Needs review",
    "review_sub": "Resumes the Lab flagged for a person to check: {rules}.",
    "why_flagged": "WHY IT WAS FLAGGED", "from_user": "From the user page", "by_admin": "Checked by {who}",
    "note": "Notes (what was done)", "note_hint": "e.g. Called the candidate, sent a new template",
    "reviewed": "Mark reviewed",
    "no_review": "No resumes need review",
    "no_review_sub": "Every flagged resume has been checked. New ones appear here by themselves.",
    "lead": "{name} · {email}",
    # settings
    "settings_title": "Settings", "settings_sub": "Changes apply to the team dashboard and the user page.",
    "rules_title": "Needs review rules", "rules_sub": "A check is flagged for the team when:",
    "links_title": "User page buttons", "links_sub": "Where the buttons on the user page go.",
    "second_title": "Second opinions", "second_sub": "Two extra ATS checkers beside the Lab score. "
                    "They are for comparison only and never change the score.",
    "server_title": "About this server",
    "server": ["Admin accounts: {admins}", "AI key set: {key}", "Data folder: {folder}",
               "Checks in the history: {checks}", "Version: ATS Lab v{version}"],
    "yes": "yes", "no": "no",
    "save": "Save settings", "reset": "Reset to server settings",
    "settings_saved": "Settings saved.", "settings_reset": "Saved settings removed: the server settings apply again.",
    "nothing_changed": "Nothing changed.",
    # activity log
    "log_title": "Activity log", "log_sub": "Everything the team does in the ATS Lab: who did it, what changed and when.",
    "stat_today": "Actions today", "stat_reviewed": "Resumes reviewed", "stat_settings": "Settings changes",
    "stat_deleted": "Records deleted",
    "log_search": "Search by admin, candidate or action",
    "col_when": "When", "col_admin": "Admin", "col_action": "Action", "col_details": "Details",
    "no_log": "Nothing has happened yet.", "no_log_match": "No actions match these filters.",
    "clear_log": "Clear the activity log",
    "clear_log_ask": "Remove every line of the Activity log? History, Needs review and the settings stay.",
    "clear_log_yes": "Clear the log",
    "clear_log_done": "{n} activity lines removed.",
    # what the page shows while a check runs
    "checking_title": "Checking the resume...",
    "checking_sub": "Reading the pages, the sections and (with a job) the job description. A few seconds.",
}

# Activity log: kind -> (filter chip, action label); the chips filter by kind
LOG_KINDS = {
    "check": ("Checks", "Checked a resume"),
    "review": ("Reviews", "Marked reviewed"),
    "settings": ("Settings", "Changed settings"),
    "delete": ("Deletions", "Deleted record"),
    "export": ("Exports", "Exported CSV"),
    "sign_in": ("Sign-ins", "Signed in"),
    "training": ("Teaching", "Set an issue aside"),
}
LOG_DETAILS = {
    "check": "{job} · score {score} · {label}",
    "review": "Note: {note}", "review_no_note": "No note",
    "review_bulk": "{n} resume{s} marked reviewed (no note)",
    "settings": "{name}: {old} → {new}", "settings_reset": "Back to the server settings",
    "delete": "Report and file removed",
    "clear_history": "Cleared the history: {checks} checks and {files} files removed",
    "clear_log": "Cleared the activity log: {n} lines removed",
    "export": "{what} · {n} record{s}", "export_history": "History", "export_log": "Activity log",
    "sign_in": "Admin page",
    "training": "Set aside ({reason})",
}

# Settings: key -> (title, description). The order here is the order on the Settings page.
SETTINGS_TEXT = {
    "file_days": ("Keep uploaded resumes",
                  "Files are deleted after this many days. Scores and reports stay in History."),
    "daily_checks": ("Free checks per day on the user page",
                     "Per person: counted by browser and by IP address, on the server."),
    "review_score": ("Score below", "A check with a lower score is flagged."),
    "review_critical": ("Any Critical issue", "A check with a Critical issue is flagged."),
    "review_contact": ("Missing email or phone", "A check without an email or a phone number is flagged."),
    "premium_url": ("“Get Premium” link", ""),
    "booking_url": ("“Book a resume session” link", ""),
    "site_url": ("“Go to 1000Jobs” link", ""),
    "collect_leads": ("Ask for name and email first",
                      "On the user page, people enter their name and email before they see the result."),
    "second_matcher": ("Resume Matcher card",
                       "Shows the second opinion card on the Admin page. It runs only when the team presses it."),
    "second_checker2": ("ATS Checker 2 card",
                        "Shows the second opinion card on the Admin page. It runs only when the team presses it."),
    "second_engine": ("ATS Checker 3 card (open-source)",
                      "Shows the open-source ats-engine card on the Admin page. It runs only when the team "
                      "presses it, on this server, and never changes the ATS Lab score."),
}
DAYS = "{n} days"

# Second opinion (Admin page only): two extra ATS checkers beside the Lab score. They read the Lab's own
# numbers and never change them. Both run on this device: no resume leaves the computer.
SECOND_TEXT = {
    "title": "Second opinion", "sub": "3 extra ATS checkers",
    "head_all": "Both checkers agree with the Lab",
    "head_some": "{n} of {total} checkers agree with the Lab",
    "head_none": "No checker agrees with the Lab",
    "note": "Second opinions are for comparison only and don't change the ATS Lab score.",
    "empty": "Not checked yet",
    "run": "Check with {name}",
    "again": "Check again",
    "checking": "Checking...",
    "checked": "Checked {when}",
    "needs_job": "Needs a job description",
    "needs_job_hint": "Check this resume with a job description to use {name}.",
    "failed": "Not available right now",
    "failed_hint": "The checker could not answer. The ATS Lab report is not affected.",
    "unavailable": "Not installed on this server",
    "unavailable_hint": "{name} needs Node.js and the open-source ats-engine package. The ATS Lab works "
                        "normally without it. See DEPLOY.md to switch it on.",
    "no_text": "No text to read",
    "no_text_hint": "This saved result carries no text: check the resume again to use {name}.",
    "off": "Switched off in Settings",
    "off_hint": "Turn {name} on in Settings to use it.",
    "vs_job": "vs Lab Job match {n}", "vs_score": "vs Lab score {n}",
    "keywords": "Keyword match", "keywords_line": "{n} of {total} keywords, {pct}%",
    "missing": "Top missing keywords: {list}",
    # what each card read, so the number is never a mystery
    "read_job": "Read: the job description's own words.",
    "read_role": "Read: the skills a {role} role is expected to have (no job description was given).",
    "read_skills": "Read: the resume's own skills list (no job description and no role were given).",
    "read_checks": "Read: this resume itself - {passed} of {total} checks passed.",
    "read_engine": "Read: the resume text with the open-source ats-engine ({version}).",
    "engine_job_match": "Job match {n}/100",
    "engine_checks": "{failed} of {total} checks failed",
    "engine_missing": "Missing keywords: {list}",
    "weakest": "Weakest: {list}",
    "no_reference": "no Job match in a general check",
    "skills": "Skills match",
    "skills_line": "{n} of {total} skills, {pct}%",
    "missing_skills": "Missing skills: {list}",
    # the benchmark: the same resume, the three checkers side by side
    "bench_title": "Benchmark: the same resume, three checkers",
    "bench_sub": "Read-only. The ATS Lab score is the first row and never changes.",
    "bench_cols": ("Checker", "Score", "Label", "Against the Lab", "What it read"),
    "bench_lab": "ATS Lab (this app)",
    "bench_lab_note": "the Lab's own score",
}

# the reasons a check needs review (also the rule names in the "Needs review" subtitle)
REVIEW_TEXT = {
    "score": "Score under {n}", "critical": "Critical issue: {names}", "no_email": "No email", "no_phone": "No phone",
    "rule_score": "a score under {n}", "rule_critical": "a Critical issue", "rule_contact": "no email or no phone",
    "rules_none": "no rule is switched on (see Settings)",
}

# ---------------------------------------------------------------------------
# User page (job seekers)
# ---------------------------------------------------------------------------
USER_TEXT = {
    "app_badge": "ATS Checker", "go_site": "Go to 1000Jobs",
    "tagline": "Resume check",
    "hero_pill": "ATS RESUME CHECK",
    "hero_1": "Can hiring systems read", "hero_2": "your resume?",
    "hero_sub": "Upload your resume and get a score, the problems that hold it back, and how to fix them. Add a job "
                "to see how well you match it.",
    "ticks": ["No account needed", "Clear score with the biggest problems first",
              "Your resume is used only to create this report"],
    "upload_title": "Check your resume",
    "uploader": "Your resume (PDF)", "drop": "Drop your resume here or", "browse": "browse",
    "drop_hint": "PDF · up to 10 MB",
    "job": "Add a job · optional", "job_add": "Add",
    "job_title": "Job title", "job_title_hint": "e.g. Brand Marketing Manager",
    "job_text": "Job description", "job_text_hint": "Paste the full job description here",
    "check": "Check my resume", "new": "Check another resume",
    "checking": "Checking your resume. This usually takes 20 to 60 seconds...",
    "limit": "You are out of limit. Go premium to try it again.",
    "privacy": "Your resume is used only to create this report. The file is deleted after {days} days.",
    "steps": [("01", "Upload", "Add your resume as a PDF, and a job if you have one in mind."),
              ("02", "Get your score", "See how readable, complete and well built your resume is."),
              ("03", "Fix what matters", "Start with the problems that lower your score the most.")],
    "need_text": "Please paste the job description too, or leave the job title empty.",
    "need_title": "Please enter the job title too.",
    "job_failed": "We could not read this job description right now. Please try again later, or check your resume "
                  "without a job.",
    "failed": "Something went wrong while checking your resume. Please try again.",
    "lead_title": "Where should we send tips about your result?",
    "lead_sub": "Enter your name and email to see your result.",
    "lead_name": "Your name", "lead_email": "Your email", "lead_go": "Show my result",
    "lead_bad": "Please enter your name and a valid email address.",
    "out_of": "out of 100",
    "headline": {"Excellent": "Your resume is in great shape", "Strong": "Your resume is in good shape",
                 "Good": "Your resume is good, with room to grow", "Needs work": "Your resume needs some work",
                 "At risk": "Your resume is at risk of being missed",
                 "Not ready": "Your resume is not ready for hiring systems yet"},
    "reach": "Fixing the issues below, it can reach about {after}.",
    "reach_none": "A few small fixes can make it even stronger.",
    "checked_job": "Checked against the job: {target}",
    "parts": "YOUR SCORE IN PARTS",
    "part_sub": {"readability": "How easily an ATS can read the file",
                 "content": "What your experience and results say",
                 "structure": "Sections, order and layout",
                 "job_match": "How well it matches the job"},
    "top": "What lowers your score most",
    "top_sub": "The issues with the biggest effect, starting with the most important.",
    "more": "+{n} more issue{s} found", "more_link": "See them with Premium",
    "issues_to_solve": "{n} issue{s} to solve",
    "none": "No issues found. Well done!",
    "cta_title": "Let 1000Jobs fix it and apply for you",
    "premium": "Get Premium", "session": "Book a resume session",
}

# the queue (both pages): only a few checks run at the same time
QUEUE_TEXT = {
    "ahead": "{n} {people} ahead of you. Your check starts automatically, please keep this page open.",
    "next": "You're next. Your check starts in a moment, please keep this page open.",
}


def plural(n):
    """'' for 1, 's' otherwise: for texts like 'record{s}'."""
    return "" if n == 1 else "s"
