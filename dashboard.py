"""
1000Jobs ATS Lab - one-page dashboard for the CV Score (cv_score.py, built on ATSLab_v3.py; neither is changed here).

  py -3.12 -m streamlit run dashboard.py

Upload one CV (PDF), optionally paste a job description (keywords are extracted once with the v3 rules and
saved in dashboard_jobs\\), and press "Check CV". Without a job the CV is checked against the 1000Jobs CV
standard (Readability, Content, Structure); with one, Job Match is added. Optional: upload a previous version
of the CV to see what was fixed.

All plain-language texts (issue names, why, how to fix, what 1000Jobs fixes) are in ISSUES below:
to add a new issue, add one entry there.
"""

import contextlib
import gc
import hashlib
import html
import importlib
import os
import re
import sys
import tempfile
import time

import streamlit as st

import ATSLab_v3 as L
import cv_cache as CC
import cv_layout as Y
import cv_review as R
import cv_score as C

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = C.MODEL
# The result format this page needs. A dashboard that keeps running while cv_score.py / cv_layout.py change on
# disk still has the OLD modules in memory (Streamlit re-runs this file only): they are reloaded when older.
SCORE_VERSION = "2026-11-09.v1.5"
# the AI recruiter review (saved per CV); ATSLAB_AI_REVIEW=0 switches it off (tests, no cost)
AI_REVIEW = os.environ.get("ATSLAB_AI_REVIEW", "1") != "0"
JOB_CACHE = os.path.join(HERE, "dashboard_jobs")   # pasted jobs + their _keywords_v3.json (extracted once)
# the dashboard's own temp folder: the uploaded PDF is written here while it is checked, then deleted
TMP_DIR = os.path.join(tempfile.gettempdir(), "atslab_dashboard")
TMP_MAX_AGE = 3600             # seconds: a temp file older than this is left over (e.g. locked) and cleaned on start
REMOVE_TRIES, REMOVE_WAIT = 6, 0.25
WITH_JOB, WITHOUT_JOB = "With job description", "Without job description"
TOP_CARDS = 6                                       # issue cards shown open; the rest under "More issues"


# ---------------------------------------------------------------------------
# Plain-language texts: ONE place. Each issue groups the internal ids it covers (bugs, checks, CV Score parts),
# says which CV lines to quote, why it hurts, how to fix it, and what 1000Jobs does about it.
# ---------------------------------------------------------------------------
ISSUES = {
    # --- can the ATS read it?
    "template": {"ids": ["TPL"], "name": "Template is hard for ATS to read", "show": "template",
                 "why": "Columns, sidebars, landscape pages and letter-spaced headings make an ATS read your resume "
                        "in the wrong order or as broken words, so your experience, dates and skills can be lost.",
                 "fix": "Use a single-column, portrait template with normal headings.",
                 "we_fix": "We rebuild your resume in a single-column, portrait template with normal headings."},
    "i_separator": {"ids": ["T12"], "name": "A capital \"I\" is used as a separator", "show": "quotes",
                    "why": "\"Designer I Brand Lead\" reads as one strange title; an ATS cannot tell that the I "
                           "separates two titles.",
                    "fix": "Use a vertical bar or a comma instead, for example \"Designer | Brand Lead\".",
                    "we_fix": "We use clear separators that every ATS reads."},
    "numbered_headings": {"ids": ["T13"], "name": "Section headings are numbered", "show": "quotes",
                          "why": "Most ATS still find \"01 PROFESSIONAL SUMMARY\", but some read the number as part "
                                 "of the heading.",
                          "fix": "Write headings without numbers, for example \"PROFESSIONAL SUMMARY\".",
                          "we_fix": "We use plain, standard section headings."},
    "icon_bullets": {"ids": ["T14"], "name": "Some bullet symbols may not display in every ATS", "show": "quotes",
                     "why": "Bullets made with icon-font symbols can show as empty boxes or odd characters in an ATS.",
                     "fix": "Use standard bullets (\u2022 or -).",
                     "we_fix": "We use standard bullets that every ATS reads."},
    "spaced_headings": {"ids": ["B1", "R5"], "name": "Section headings are hard to read", "show": "spaced",
                        "why": "The ATS reads letter-spaced headings like \"E D U C A T I O N\" as single letters, "
                               "so it may not find your sections.",
                        "fix": "Write every heading as a normal word, for example \"Education\".",
                        "we_fix": "Our template writes every heading as a plain, standard word."},
    "skills_unreadable": {"ids": ["B2", "R9"], "name": "Skills section is hard to read", "show": "skills_ats",
                          "why": "The ATS cannot pick out your individual skills, so they may not count in a "
                                 "recruiter's search.",
                          "fix": "List your skills as plain words separated by commas under a \"Skills\" heading.",
                          "we_fix": "We list your skills as clean, searchable words."},
    "watermark": {"ids": ["B3"], "name": "Extra text appears inside your resume", "show": "watermark",
                  "why": "The ATS reads the \"Prepared with\" note as part of your resume and mixes it into your content.",
                  "fix": "Remove the note from the resume text.",
                  "we_fix": "We remove notes and labels that do not belong in your resume."},
    "email": {"ids": ["B4", "R2", "T7"], "name": "Email address is missing", "show": "header",
              "why": "Recruiters cannot contact you, and some ATS reject a resume without an email.",
              "fix": "Add your email address at the top of the resume.",
              "we_fix": "We put your full contact details at the top where every ATS looks."},
    "markdown": {"ids": ["B5"], "name": "Formatting marks (**) show as text", "show": "markdown",
                 "why": "The ATS shows the ** marks as text, which looks broken to a recruiter.",
                 "fix": "Remove the ** marks and use normal bold text instead.",
                 "we_fix": "We clean every formatting mark out of the text."},
    "html": {"ids": ["B6"], "name": "Web code shows as text", "show": "html",
             "why": "Pieces of web code like <span> are shown to the recruiter as text.",
             "fix": "Remove the code so only normal text is left.",
             "we_fix": "We clean every formatting mark out of the text."},
    "placeholder": {"ids": ["B7"], "name": "Unfinished placeholder text", "show": "placeholder",
                    "why": "Text like \"Not Specified\" tells the recruiter that information is missing.",
                    "fix": "Replace the placeholder with the real information, or remove the line.",
                    "we_fix": "We fill in or remove every unfinished line with you."},
    "glance_boxes": {"ids": ["B8"], "name": "Highlight boxes are read in the wrong order", "show": "glance",
                     "why": "The ATS reads boxes placed side by side line by line, so their numbers and words "
                            "get mixed up.",
                     "fix": "Put each highlight on its own line, one under the other.",
                     "we_fix": "Our single-column layout keeps every highlight in reading order."},
    "dates": {"ids": ["B11", "R6", "R7"], "name": "Job dates are missing or incomplete", "show": "dates",
              "why": "Without a month and year for each job, the ATS cannot work out your experience.",
              "fix": "Give every job a start and end date with month and year, for example \"Mar 2021 - Jun 2023\".",
              "we_fix": "We write every job date as month and year, the format every ATS reads."},
    "backticks": {"ids": ["B12"], "name": "Formatting marks (`) show as text", "show": "backticks",
                  "why": "The ATS shows the ` marks as text, which looks broken to a recruiter.",
                  "fix": "Remove the ` marks.",
                  "we_fix": "We clean every formatting mark out of the text."},
    "name": {"ids": ["R1"], "name": "Your name is not clear at the top", "show": "header",
             "why": "The ATS takes the first line as your name; if it is unclear, your profile is saved wrongly.",
             "fix": "Put your full name alone on the first line.",
             "we_fix": "We put your name alone on the first line."},
    "phone": {"ids": ["R3", "T3"], "name": "Phone number is not in +country-code format", "show": "contact",
              "why": "Without a clear +country code, recruiters abroad may not be able to call you, and an ATS may "
                     "save the number broken (for example \"+971) 585-...\").",
              "fix": "Write the phone number as +country code and number, without brackets, for example "
                     "+971 50 123 4567.",
              "we_fix": "We write your phone number with its country code."},
    "headline": {"ids": ["R4", "C15"], "name": "No headline with a target title under your name", "show": "header",
                 "why": "The line under your name is the first thing a recruiter reads about you; it should say "
                        "which role you are aiming for.",
                 "fix": "Add one short line under your name with your target job title and main strengths.",
                 "we_fix": "We write a headline that names your target role and strengths."},
    "section_names": {"ids": ["R11", "T1"], "name": "Some section names are unusual", "show": "quotes",
                      "why": "Strict systems like Workday and Oracle only recognise standard section names.",
                      "fix": "Use standard names: Summary, Experience, Education, Skills, Certifications, Languages "
                             "and Additional Information.",
                      "we_fix": "We use the standard section names every ATS knows."},
    "core_sections": {"ids": ["R12"], "name": "A main section is missing", "show": "sections_ats",
                      "why": "The ATS expects a Summary, Experience, Education and Skills section.",
                      "fix": "Add the missing section with a standard name.",
                      "we_fix": "Every resume we write has Summary, Experience, Education and Skills."},
    "few_details": {"ids": ["C18"], "name": "Few details about your roles", "show": "quotes",
                    "why": "With only a few bullets per role, a recruiter cannot see what you did and achieved.",
                    "fix": "Give each role of the last 10 years about 3 bullets, each with what you did and what changed.",
                    "we_fix": "We write about 3 clear bullets for each recent role from your real experience."},
    "summary_bullets": {"ids": ["C17"], "name": "Summary is written as bullets", "show": "quotes",
                        "why": "A summary in bullets reads like a list of duties; a recruiter skims one short paragraph "
                               "faster.",
                        "fix": "Write the summary as one short paragraph (about 40 to 90 words) without bullets.",
                        "we_fix": "We write the summary as one short paragraph built around your target role."},
    "summary": {"ids": ["C4", "R13"], "name": "Summary is over 150 words", "show": "summary",
                "why": "A very long summary gets skipped; the recruiter wants to know who you are in a few lines.",
                "fix": "Cut the summary to a short paragraph of 150 words at most.",
                "we_fix": "We write a focused summary built around your target role."},
    "name_spacing": {"ids": ["N1"], "name": "Name has letter spacing", "show": "spaced",
                     "why": "The ATS may read a letter-spaced name as single letters, so your "
                            "profile can be saved under a wrong name.",
                     "fix": "Write your name with normal spacing; make it bigger or bold instead.",
                     "we_fix": "We write your name in normal letters, larger and bold, so every ATS reads it."},
    # --- is the content strong?
    "numbers": {"ids": ["C1"], "name": "Few bullets show numbers or results", "show": "quotes",
                "why": "Recruiters trust results they can measure; a bullet without a number reads like a duty list.",
                "fix": "Add a number to each bullet where you can: how many, how much, how fast, or by what percent.",
                "we_fix": "We work with you to turn duties into measurable results."},
    "buzzwords": {"ids": ["C5", "B10"], "name": "Generic buzzwords or template phrases", "show": "quotes",
                  "why": "Words like \"results-driven\" or a repeated \"approximately\" appear in thousands of resumes "
                         "and prove nothing.",
                  "fix": "Replace each buzzword with a fact about your own work, and drop repeated filler words.",
                  "we_fix": "We replace buzzwords with facts from your own experience."},
    "repeated": {"ids": ["C6", "B9", "B13"], "name": "Some text is repeated", "show": "quotes",
                 "why": "Repeating the same points makes the resume longer without adding anything new.",
                 "fix": "Keep each point in one place only.",
                 "we_fix": "We remove repeats so every line adds something new."},
    "repeated_numbers": {"ids": ["C9"], "name": "The same result is repeated", "show": "quotes",
                         "why": "Repeating one result (for example \"$25M\" four times) makes the resume look like it "
                                "has fewer achievements than it really has.",
                         "fix": "Tell each result once, in the place where it fits best.",
                         "we_fix": "We use each result once, where it counts most."},
    "job_labels": {"ids": ["C10"], "name": "Labels inside jobs", "show": "quotes",
                   "why": "Lines like \"Key Accomplishments:\" or \"Responsibilities:\" take space and break the "
                          "flow of the job.",
                   "fix": "Remove the labels and keep the bullets under the job title.",
                   "we_fix": "We write each job as a short intro and clean bullets, without labels."},
    "weak_openers": {"ids": ["C11", "C2"], "name": "Bullets start with weak words", "show": "quotes",
                     "why": "\"Responsible for\", \"Helped\", \"Assisted\" or \"Participated in\" describe a duty, "
                            "not what you achieved.",
                     "fix": "Start with what you did and what changed, for example \"Reduced ... by 20%\".",
                     "we_fix": "We rewrite every bullet to start with a strong action verb."},
    "abbreviations_full": {"ids": ["C12"], "name": "Abbreviations are never written in full", "show": "quotes",
                           "why": "A recruiter may not know a short form such as CRM, and some search for the "
                                  "full words.",
                           "fix": "Write it in full once, for example \"Customer Relationship Management (CRM)\".",
                           "we_fix": "We write key terms in both their short and long form."},
    "old_roles": {"ids": ["C13"], "name": "Old roles have too many bullets", "show": "quotes",
                  "why": "Roles that ended more than 10 years ago matter less; long lists there push your recent "
                         "work down.",
                  "fix": "Keep at most 2 bullets for each role that ended 10 or more years ago.",
                  "we_fix": "We keep older roles short so your recent work stands out."},
    "tense": {"ids": ["C14"], "name": "Past jobs written in the present tense", "show": "quotes",
              "why": "Mixing tenses makes it unclear which work you still do.",
              "fix": "Write past jobs in the past tense (\"Managed\", not \"Manage\").",
              "we_fix": "We write past jobs in the past tense and your current job in the present."},
    "education_items": {"ids": ["T2"], "name": "Non-degree items under Education", "show": "quotes",
                        "why": "Programs, challenges and courses under Education hide your real degree.",
                        "fix": "Keep only degrees under Education; move courses to Certifications or Additional "
                               "Information.",
                        "we_fix": "We keep only degrees under Education and move the rest to the right section."},
    "same_result": {"ids": ["C16"], "name": "The same result has different numbers", "show": "quotes",
                    "why": "When one result is told with different numbers in different places, a recruiter "
                           "stops trusting all of your numbers.",
                    "fix": "Check the real figure and use the same numbers everywhere you mention this result.",
                    "we_fix": "We check every number against your records and use one figure per result."},
    "merged_titles": {"ids": ["T11"], "name": "Two job titles written as one", "show": "quotes",
                      "why": "\"Senior / Media Manager\" reads as one unclear title; an ATS and background checks "
                             "look for each title as you held it.",
                      "fix": "Write each title on its own line with its own dates, for example \"Media Manager\" "
                             "then \"Senior Media Manager\".",
                      "we_fix": "We list each title you held on its own line with its own dates."},
    "uae_details": {"ids": ["T10"], "name": "No visa status, driving licence or notice period", "show": "contact",
                    "why": "UAE employers often screen on visa status, a UAE driving licence and the notice period.",
                    "fix": "If true, add an \"Additional Information\" line, for example \"Visa: UAE residence "
                           "visa | UAE driving licence | Notice period: 30 days\". Leave out anything that is not "
                           "true.",
                    "we_fix": "We add your visa status, driving licence and notice period, only if they are true."},
    "length": {"ids": ["C7"], "name": "Resume is short for your experience", "show": "length",
               "why": "A short resume undersells your experience: a recruiter cannot see enough of what you did.",
               "fix": "Add more about your recent roles: what you did and what changed. With 10 or more years of "
                      "experience, two pages are normal.",
               "we_fix": "We give your experience the room it needs, using only what you really did."},
    # --- does it fit the role?
    "skills_missing": {"ids": ["K", "F1", "M1"], "name": "Important skills for the role are missing", "show": "skills_missing",
                       "why": "Recruiters search the ATS for these skills; if they are not in your resume, it is not found.",
                       "fix": "Add the missing skills you really have, in your skills list and in your bullets.",
                       "we_fix": "We match your real skills to the words recruiters search for.",
                       # without a job description the list is common skills for the role, not one employer's words
                       "role_compared": "Compared with skills for: {role} (from your resume)",
                       "role_compared_user": "Compared with skills for: {role}",
                       "role_note": "Commonly requested for this role. Add them only if you've really used them.",
                       "role_career": "Your experience is mainly in {field}. This role is a career change, so "
                                      "expect a bigger skills gap.",
                       "role_transferable": "Transferable skills your resume already shows: {skills}"},
    # --- found by the AI reviewer (title, quote, why and fix come from the review; these are the fallbacks)
    "ai_finding": {"ids": [], "name": "Found by the AI reviewer", "show": "quotes",
                   "label": "AI suggestion",
                   "confirmed": "AI suggestion, confirmed by the Lab's own check",
                   "why": "A recruiter reading this part of the resume would notice the problem.",
                   "fix": "Rewrite this part using only your real experience.",
                   "we_fix": "We rewrite the parts a recruiter would question, using only your real experience."},
    "abbreviations": {"ids": ["F2"], "name": "Abbreviations are written only one way", "show": "abbreviations",
                      "why": "Some recruiters search for the short form and others for the long form.",
                      "fix": "Write both forms once, for example \"Search Engine Optimization (SEO)\".",
                      "we_fix": "We write key terms in both their short and long form."},
    "job_title": {"ids": ["F3"], "name": "The job title is not near the top", "show": "header",
                  "why": "The ATS ranks a resume higher when the exact job title appears in the headline or summary.",
                  "fix": "Use the exact job title from the job description in your headline or summary.",
                  "we_fix": "We put the exact job title in your headline."},
    "past_titles": {"ids": ["F4"], "name": "Past job titles were changed", "show": "job_lines",
                    "why": "Background checks compare your job titles with your employers' records.",
                    "fix": "Keep your past job titles exactly as they were.",
                    "we_fix": "We keep your real job titles exactly as they were."},
    "meaning": {"ids": ["M3"], "name": "Your experience reads as a weak fit for the job", "show": "summary",
                "why": "The ATS compares the meaning of your resume with the job; your experience reads as a weak fit.",
                "fix": "Describe the parts of your experience that match the job's main duties.",
                "we_fix": "We bring forward the experience that matches the job."},
    "education_fit": {"ids": ["M4"], "name": "Education does not match the job", "show": "education",
                      "why": "The job asks for a degree level or subject that the ATS could not find in your resume.",
                      "fix": "Show your degree level and subject clearly in the Education section.",
                      "we_fix": "We show your degree level and subject clearly."},
    "experience": {"ids": ["M5"], "name": "Fewer years of experience than the job asks", "show": "dates",
                   "why": "The ATS adds up your job dates and compares them with the years the job asks for.",
                   "fix": "Make sure every relevant job is listed with full dates.",
                   "we_fix": "We list every relevant job with full dates."},
    # --- is it complete?
    "linkedin": {"ids": ["P1", "T5"], "name": "No LinkedIn profile link", "show": "contact",
                 "why": "Most recruiters check LinkedIn; without the link they may not look further.",
                 "fix": "Add your LinkedIn profile link next to your email and phone.",
                 "we_fix": "We add your LinkedIn link to the contact line."},
    "skills_section": {"ids": ["P2", "T8"], "name": "Skills section is missing or very short", "show": "skills_page",
                       "why": "The skills section is where the ATS looks first for searchable skills.",
                       "fix": "Add a skills section with at least 8 skills you really have.",
                       "we_fix": "We build a skills section from your real experience."},
    "certifications": {"ids": ["P3"], "name": "No certifications listed", "show": "sections_page",
                       "why": "Certifications are easy for recruiters to search and quick proof of your skills.",
                       "fix": "Add any certifications or courses you have completed, with the year.",
                       "we_fix": "We list your certifications and courses in their own section."},
    "education_details": {"ids": ["R8", "P4", "T9"], "name": "Education details are incomplete", "show": "education",
                          "why": "Recruiters expect the degree, the school and the year for each qualification.",
                          "fix": "Write the degree, the school and the year for each qualification.",
                          "we_fix": "We list each degree with its school and year."},
    "job_details": {"ids": ["P5", "T4"], "name": "Some jobs miss a title or a company", "show": "quotes",
                    "why": "Each job needs a title and a company, or the ATS cannot build your work history.",
                    "fix": "Give every job its title and company name.",
                    "we_fix": "We give every job its title and company."},
    # 2026-11-09: the one job card became three separate messages, each with its own evidence, so the text always
    # matches what the resume really shows: dates missing, dates not Mon YYYY, and no experience section found.
    "job_dates_missing": {"ids": ["T4B"], "name": "Job dates are missing", "show": "quotes",
                          "why": "Without dates the ATS cannot tell how long you stayed, and some systems drop the "
                                 "job or place it in the wrong order.",
                          "fix": "Add the start and end month and year to every job, for example \"Jan 2021 - "
                                 "Present\".",
                          "we_fix": "We write every job's start and end dates as month and year."},
    "job_dates_format": {"ids": ["T4C"], "name": "Job dates are not written as Mon YYYY", "show": "quotes",
                         "why": "A year alone, or a length such as \"2 years\", cannot be read as a date by the "
                                "ATS, so your timeline looks incomplete.",
                         "fix": "Write each date as month and year, for example \"Mar 2018 - Dec 2020\".",
                         "we_fix": "We convert every job date to the month and year format."},
    "no_experience": {"ids": ["T4D"], "name": "No work experience section was found", "show": "quotes",
                      "why": "When the experience section cannot be read, the ATS sees no work history at all, which "
                             "is the most damaging thing that can happen to an application.",
                      "fix": "Keep one clear \"Experience\" heading and list the jobs underneath it, not inside "
                             "boxes, tables or columns.",
                      "we_fix": "We give every resume a standard Experience section the ATS can read."},
    "printed_code": {"ids": ["T18"], "name": "Printed code or HTML is visible in the text", "show": "quotes",
                     "why": "The ATS reads the code as text, so a date or a whole job line can be lost, and the "
                            "recruiter sees the code.",
                     "fix": "Remove the code from the resume text, or export a clean text version.",
                     "we_fix": "We export every resume so no code is left in the text."},
    "job_locations": {"ids": ["T16"], "name": "Some jobs show no location", "show": "quotes",
                      "why": "A place next to a job helps recruiters who filter by city, but it is not required.",
                      "fix": "Add the city and country next to the company when you want to, for example \"Dubai, UAE\".",
                      "we_fix": "We add the city and country to each job line when you have them."},
    "program_entry": {"ids": ["T17"], "name": "A course or program is listed under Experience", "show": "quotes",
                      "why": "Recruiters read everything under Experience as a job, so a course or program can look "
                             "like work you were paid for.",
                      "fix": "Move it to Certifications or Professional Development.",
                      "we_fix": "We list courses and programs under Certifications, not under Experience."},
    "location": {"ids": ["P6", "T6"], "name": "No city in the contact details", "show": "contact",
                 "why": "Many recruiters filter candidates by city or country.",
                 "fix": "Add your city and country, for example \"Dubai, UAE\".",
                 "we_fix": "We add your city and country to the contact line."},
    # --- design and layout (read from the PDF itself)
    "photo": {"ids": ["D1"], "name": "Photo or images on the resume", "show": "quotes",
              "why": "Most ATS cannot read images; some drop them, others show an empty box or skip that part.",
              "fix": "Keep a photo version for direct emails, and use an ATS version without the photo for "
                     "online applications.",
              "we_fix": "We prepare two versions: one with your photo for direct emails and one without it for "
                        "online applications."},
    "colored_panels": {"ids": ["D2"], "name": "Colored backgrounds or shading", "show": "quotes",
                       "why": "Some ATS skip text inside colored shapes, and the text can disappear when the "
                              "background is removed.",
                       "fix": "Use a plain white background and mark sections with simple headings.",
                       "we_fix": "Our template uses a clean white page with simple headings."},
    "page_format": {"ids": ["T15"], "name": "The page is not a standard resume page", "show": "quotes",
                    "why": "A standard resume is a portrait page in one column; landscape pages, columns and "
                           "sidebars are not built the way an ATS expects a resume to be.",
                    "fix": "Move your resume to a single-column, portrait page.",
                    "we_fix": "We rebuild your resume as a single-column, portrait page."},
    "image_page": {"ids": ["D13"], "name": "A page is an image", "show": "quotes",
                   "why": "An ATS reads no text on a page that is an image, so everything on it is lost.",
                   "fix": "Keep every page as real text; put designed pages in a separate file for direct emails.",
                   "we_fix": "We keep every page of your resume as real, readable text."},
    "sidebar": {"ids": ["D3"], "name": "Sidebar layout", "show": "quotes",
                "why": "An ATS reads the sidebar and the main column line by line together, so their text gets mixed.",
                "fix": "Move the sidebar content into the main column, in a single-column layout.",
                "we_fix": "We rebuild your resume in one clean column."},
    "columns": {"ids": ["D4"], "name": "Two or more columns", "show": "quotes",
                "why": "Most ATS read straight across the page, mixing lines from different columns.",
                "fix": "Use a single-column layout that reads from top to bottom.",
                "we_fix": "We rebuild your resume in one clean column."},
    "icons": {"ids": ["D5"], "name": "Icons used for contact details", "show": "quotes",
              "why": "An ATS cannot read icons, so it may not know which line is your phone, email or location.",
              "fix": "Write the contact details as plain text, with a word label if needed, for example "
                     "\"Phone: +971 ...\".",
              "we_fix": "We write your contact details as plain text an ATS understands."},
    "boxes": {"ids": ["D6"], "name": "Text inside boxes or tables", "show": "quotes",
              "why": "Many ATS skip or scramble text placed inside shapes, boxes or tables.",
              "fix": "Take the text out of boxes and tables and write it as normal lines.",
              "we_fix": "We move every piece of text out of boxes and tables."},
    "fonts": {"ids": ["D7"], "name": "Fonts are too small, too many or decorative", "show": "quotes",
              "why": "Text under 9 pt is hard to read, and unusual or mixed fonts can be misread by an ATS.",
              "fix": "Use one or two standard fonts, with body text of at least 10 pt.",
              "we_fix": "We use one standard font at a readable size."},
    "contrast": {"ids": ["D8"], "name": "Light or low-contrast text", "show": "quotes",
                 "why": "Light text on a colored background is hard to read and can vanish when the background "
                        "is removed.",
                 "fix": "Use dark text on a white background.",
                 "we_fix": "We use dark text on a white page."},
    "only_in_sidebar": {"ids": ["D9"], "name": "Contact details or skills only in the sidebar", "show": "quotes",
                        "why": "If the ATS skips or mixes up the sidebar, your contact details or skills are lost.",
                        "fix": "Put your contact details at the top of the page and your skills in the main column.",
                        "we_fix": "We put your contact details at the top and your skills in the main column."},
    "reading_order": {"ids": ["D10"], "name": "The ATS reads your sections in the wrong order", "show": "quotes",
                      "why": "The ATS reads across the page, so your sections arrive mixed up and in a different "
                             "order than on the page.",
                      "fix": "Use a single column so the resume reads simply from top to bottom.",
                      "we_fix": "We rebuild your resume in one clean column that reads from top to bottom."},
    "pages": {"ids": ["D11"], "name": "Too many pages for your experience", "show": "page_count",
              "why": "Recruiters spend seconds on a resume; extra pages bury your best work.",
              "fix": "Keep the resume to one page under 3 years of experience and two pages for most careers.",
              "we_fix": "We fit your resume to the right length for your experience."},
}
ISSUE_OF = {i: key for key, v in ISSUES.items() for i in v["ids"]}
# A fix worth ~0 points because another part holds the score down: what to fix first (then it adds about +X)
BLOCKED_FIRST = {"readability": "Fix the layout issues first", "content": "Fix the content issues first",
                 "job_match": "Add the missing skills first", "structure": "Fix the structure issues first",
                 "numbers": "Add numbers or results to your bullets first"}
PART_NAMES = {"readability": "Readability", "content": "Content", "structure": "Structure",
              "job_match": "Job Match"}
SHOWN_SEVERITY = {"Critical": "Critical", "Major": "Important", "Minor": "Minor"}
EDU_HINT_RE = re.compile(r"\b(b\.\s?s\.|m\.\s?s\.|b\.\s?a\.|degree|university|college|diploma|graduat)", re.I)
CODE_RE = re.compile(r"\b(?:[BRFMCPDNT]\d{1,2}|K)\b")    # internal ids: must never appear on the page
# Part cards: what is good (shown when none of these issues was found), at most 2
GOOD = {
    "readability": [({"TPL", "D3", "D4", "D9", "D10", "B8"}, "One column that an ATS reads in the right order"),
                    ({"B1", "R5", "N1", "B2", "R9"}, "Name, headings and skills are easy for an ATS to read"),
                    ({"B3", "B5", "B6", "B7", "B12", "R10"}, "No broken text or stray marks"),
                    ({"D1", "D2", "D5", "D6", "D7", "D8"}, "Clean design: no photo, icons or boxes")],
    "content": [({"C15"}, "A headline names your target role"),
                ({"C1"}, "Most bullets show numbers or results"),
                ({"C2", "C11"}, "Bullets start with strong action verbs"),
                ({"C4"}, "The summary is one short paragraph"),
                ({"C5", "C9", "C6"}, "No buzzwords or repeated results")],
    "structure": [({"T7", "T3", "T5", "T6", "B4"}, "Full contact details: email, phone, LinkedIn and city"),
                  ({"T4", "B11"}, "Every job has a title, company and dates"),
                  ({"T1"}, "Standard section names"),
                  ({"T8"}, "A skills section with real skills"),
                  ({"T2", "T9"}, "EDUCATION")],
    "job_match": [({"K", "F1", "M1"}, "Has the skills this job asks for"),
                  ({"F3"}, "The job title appears near the top"),
                  ({"M5"}, "Enough years of experience for the job"),
                  ({"M4"}, "Education fits the job")],
}
WHY_TEXT = {"blocked": "{first}: until then, fixes here add little to your Resume Score."}
MAX_WHY_GOOD, MAX_WHY_ISSUES = 2, 5
# "How 1000Jobs will improve your resume": every text of this section is here
IMPROVE_TEXT = {
    "title": "How 1000Jobs will improve this resume",
    "sub": "Each fix comes from a problem found above.",
    "fix_title": "What we'll fix",
    "found": "Found in your resume: {issue}",
    "nothing": "Your resume already meets our standard. We keep what works and tailor it for each job.",
    "why_title": "Why 1000Jobs",
    "why": ["We'll make your resume professional, clear and ready for any ATS.",
            "We'll tailor your resume for every application, using each job's own keywords.",
            "More applications, less effort: we send tailored applications for you, so you reach more employers."],
}
# the client comparison report (the client's original resume next to our 1000Jobs resume): every text is here.
# Problems are only ever described from the ORIGINAL resume; the 1000Jobs resume shows only its scores.
CLIENT_TEXT = {
    "checkbox": "The main resume is a 1000Jobs resume (client comparison report)",
    "need_original": "Upload the original resume under \"Compare with a previous resume\" to make the client "
                     "comparison report.",
    "report_title": "1000Jobs ATS Lab - Resume Comparison", "file_kind": "Comparison",
    "original_file": "Original resume", "ours_file": "1000Jobs resume",
    "compared": "Compared",
    "compared_sub": "The same checks on both resumes: how easily an ATS reads them and how well they meet the "
                    "1000Jobs resume standard.",
    "original": "Original resume: {score}", "ours": "1000Jobs resume: {score}", "change": "{sign}{change}",
    "part": "Part", "col_original": "Original", "col_ours": "1000Jobs", "col_change": "Change",
    "improved": "Improved",
    "improved_sub": "Issues found in the original resume that are fixed in the 1000Jobs resume.",
    "none_improved": "No issue of the original resume was fixed.",
    "before": "Before", "changed": "What changed",
    "issues": "Issues in the original resume",
    "issues_sub": "Every issue found in the original resume, most important first.",
    "no_issues": "No issues were found in the original resume.",
    "quote": "In the original resume",
    "swapped": "The two files were given the other way round: the one with the 1000Jobs layout ({ours}) is the "
               "1000Jobs resume, so {original} is read here as the original resume.",
}
MAX_QUOTE_LINES, MAX_QUOTE_CHARS = 2, 160     # "before" quotes in the client report: short
MAX_IMPROVE = 4                # "What we'll fix": at most this many lines, each tied to an issue in this resume
MAX_PROMISE = 95               # "can reach about X": never more than this


JOB_TITLE_MISSING = "Please enter the target role (job title, for example \"Brand Marketing Manager\"). It is required with a job description."


class CheckError(Exception):
    """A problem the user can fix (shown as a clear message, not a crash)."""


# what the user reads when a file cannot be checked (no technical words)
CHECK_TEXT = {
    "no_file": "Please upload a resume first.",
    "empty": "This file is empty.",
    "word": "Please save your resume as a PDF and upload it again.",
    "not_pdf": "'{name}' is not a PDF file. Please upload the resume as a PDF.",
    "locked": "This PDF is locked with a password. Save it without a password and upload it again.",
    "damaged": "We could not open '{name}'. The file may be damaged. Please save it as a PDF again and upload it again.",
    "no_text": "No text found in '{name}'. It may be a scanned image: an ATS cannot read it either.",
    "not_english": "We currently check resumes in English. Please upload an English version.",
    "not_resume": "This doesn't look like a resume. Please upload your resume as a PDF.",
}
UPLOAD_TYPES = ["pdf", "doc", "docx"]      # a Word file is accepted by the upload box, then gets a clear message
MIN_TEXT_WORDS = 30                         # fewer words than this: a picture of a resume, not readable text
LOCKED_ERRORS = ("PDFPasswordIncorrect", "PDFEncryptionError")


def is_word_file(pdf_bytes, filename):
    """A Word document (.doc / .docx), also one renamed to .pdf."""
    head = pdf_bytes[:8]
    return (filename or "").lower().endswith((".doc", ".docx")) or head.startswith(b"\xd0\xcf\x11\xe0") or \
        (head.startswith(b"PK\x03\x04") and b"word/" in pdf_bytes[:4096])


def is_locked(error):
    """The PDF reader stopped because the file needs a password."""
    while error is not None:
        if type(error).__name__ in LOCKED_ERRORS:
            return True
        error = error.__cause__ or error.__context__
    return False


# ---------------------------------------------------------------------------
# Logic (no Streamlit here, so it can be tested directly)
# ---------------------------------------------------------------------------
def job_file(job_text, cache=None):
    """The saved job for this text: same text (ignoring spaces) -> same file -> keywords reused."""
    key = hashlib.sha256(" ".join(job_text.split()).encode("utf-8")).hexdigest()[:16]
    return os.path.join(cache or JOB_CACHE, f"job_{key}.txt")


LAB_MODULES = (CC, L, Y, R, C)      # in the order they import each other


def fresh_modules():
    """Same file, same score: a dashboard that keeps running while the Lab's files change on disk reloads ALL of them
    (ATSLab_v3, cv_layout, cv_review, cv_score), never only some, so it never scores with a mix of old and new rules.
    A module is stale when its file changed since it was loaded, or when cv_score is not the version this page needs."""
    stale = getattr(C, "SCORE_VERSION", None) != SCORE_VERSION or         any(getattr(m, "_lab_mtime", None) != os.path.getmtime(m.__file__) for m in LAB_MODULES)
    if stale:
        for m in LAB_MODULES:
            importlib.reload(m)
            m._lab_mtime = os.path.getmtime(m.__file__)
    return stale


def is_current(r):
    """A result made by the scoring this page expects (has the layout data, same version)."""
    return isinstance(r, dict) and r.get("version") == SCORE_VERSION and "layout" in r


AI_BUSY_TEXT = ("The AI service is busy right now, so this job could not be read. Nothing was checked - press "
                "Run check again in a minute.")


def message_of_ai_error(text):
    """The message the team sees when the Lab stopped on an AI problem. A service that is busy or unreachable becomes
    one plain sentence (the provider's own answer is written to the server log, never shown); anything else keeps the
    Lab's own words."""
    low = (text or "").lower()
    if "the ai service is busy" in low or "no valid keyword answer" in low:
        print(f"AI check stopped: {text}", file=sys.stderr)
        return AI_BUSY_TEXT
    return f"Keyword extraction failed: {text}"


def run_check(pdf_bytes, filename, with_job, text, cache=None, role_cache=None, job_title=None):
    """CV Score for one CV. with_job: text = the job description and job_title = the job's title, typed by the user
    (required: it is never guessed from the posting); else text = an optional target role (empty: the role is
    taken from the CV itself)."""
    fresh_modules()
    if not pdf_bytes:
        raise CheckError(CHECK_TEXT["empty" if filename else "no_file"])
    if is_word_file(pdf_bytes, filename):
        raise CheckError(CHECK_TEXT["word"])
    if not pdf_bytes.lstrip()[:5] == b"%PDF-":
        raise CheckError(CHECK_TEXT["not_pdf"].format(name=filename))
    text = (text or "").strip()
    job_path, role = None, None
    if with_job:
        if not text:
            raise CheckError("The job description is empty. Paste the full job description first.")
        why = L.not_a_job_reason(text)
        if why:
            raise CheckError(f"This does not look like a job description: {why}.")
        job_title = " ".join((job_title or "").split())
        if not job_title:
            raise CheckError(JOB_TITLE_MISSING)
        job_path = job_file(text, cache)
        if not os.path.exists(L.keywords_path(job_path)) and not os.environ.get("OPENROUTER_API_KEY"):
            raise CheckError("The OpenRouter API key is missing, so the job keywords cannot be extracted. "
                             "Set OPENROUTER_API_KEY (an environment variable or a Streamlit secret, see DEPLOY.md), "
                             "then start the Lab again.")
        os.makedirs(os.path.dirname(job_path), exist_ok=True)
        if not os.path.exists(job_path):
            with open(job_path, "w", encoding="utf-8") as f:
                f.write(text)

    os.makedirs(TMP_DIR, exist_ok=True)
    fd, pdf_path = tempfile.mkstemp(suffix=".pdf", dir=TMP_DIR)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(pdf_bytes)
        with contextlib.ExitStack() as parsed:      # the PDF is parsed once for every reading of this check
            try:
                parsed.enter_context(CC.one_parse(pdf_path))
                doc = L.extract_cv(pdf_path)
            except Exception as e:
                raise CheckError(CHECK_TEXT["locked" if is_locked(e) else "damaged"].format(name=filename))
            if len(doc["modern"].split()) < MIN_TEXT_WORDS:
                raise CheckError(CHECK_TEXT["no_text"].format(name=filename))
            if C.not_english(doc["modern"]):        # checked before the score (and before any AI call)
                raise CheckError(CHECK_TEXT["not_english"])
            if not C.resume_signs(doc):
                raise CheckError(CHECK_TEXT["not_resume"])
            try:
                review = AI_REVIEW and bool(os.environ.get("OPENROUTER_API_KEY"))
                try:
                    r = C.score_cv(pdf_path, job_path, role, MODEL, doc=doc, role_cache=role_cache, review=review,
                                   job_title=job_title)
                except OSError as e:
                    if not is_native_fault(e):
                        raise
                    # a library hit a CPU instruction this computer lacks: check again without the native parts
                    r = C.score_cv(pdf_path, job_path, role, MODEL, doc=doc, role_cache=role_cache, review=review,
                                   safe=True, job_title=job_title)
                if not is_current(r):
                    raise CheckError("The scoring code on disk is older than this page. Restart the dashboard.")
            except C.ScoreError as e:
                raise CheckError(str(e))
            except L.NotAJob as e:
                raise CheckError(f"This does not look like a job description: {e}.")
            except SystemExit as e:                 # v3 stops with a message (API error, missing key, ...)
                raise CheckError(message_of_ai_error(str(e)))
    finally:
        safe_remove(pdf_path)                       # never fails the check (Windows may hold the file a moment)
    r["cv"] = filename
    r["_size"] = len(pdf_bytes)
    r["v3"]["cv"] = filename
    r["_doc"] = r.get("_doc") or doc               # for quotes from the CV (headers / footers left out)
    return r


# Windows status codes of a native library crashing inside a call (seen as OSError [WinError ...] through ctypes)
NATIVE_FAULTS = {-1073741795: "illegal instruction", -1073741819: "access violation",
                 -1073741571: "stack overflow", -1073741676: "integer divide by zero"}


def is_native_fault(e):
    """True for OSError [WinError -1073741795] (0xC000001D, an unsupported CPU instruction) and similar crashes."""
    code = getattr(e, "winerror", None)
    return code in NATIVE_FAULTS or any(f"{c & 0xFFFFFFFF:#010x}" in str(e).lower() for c in NATIVE_FAULTS)


def safe_remove(path, tries=None, wait=None):
    """Delete a temp file. On Windows another program (an antivirus scan, the search indexer) can hold a fresh file
    for a moment: try again a few times; if it is still held, leave it for clean_temp(). Never raises.
    -> True when the file is gone."""
    tries = REMOVE_TRIES if tries is None else tries
    wait = REMOVE_WAIT if wait is None else wait
    gc.collect()                                   # objects still holding the PDF (an error halfway) are freed
    for k in range(tries):
        try:
            os.remove(path)
            return True
        except FileNotFoundError:
            return True
        except OSError:                            # PermissionError [WinError 32]: in use by another process
            if k < tries - 1:
                time.sleep(wait * (k + 1))
    return False


def clean_temp(max_age=None, folder=None):
    """Delete the dashboard's left-over temp files (older than max_age seconds). Never raises. -> files deleted."""
    max_age = TMP_MAX_AGE if max_age is None else max_age
    folder = folder or TMP_DIR
    gone = 0
    try:
        names = os.listdir(folder)
    except OSError:
        return 0
    now = time.time()
    for name in names:
        path = os.path.join(folder, name)
        try:
            if os.path.isfile(path) and now - os.path.getmtime(path) >= max_age:
                os.remove(path)
                gone += 1
        except OSError:
            pass                                   # still in use: next time
    return gone


def _lines(text, pattern, limit=4):
    pat = re.compile(pattern, re.I) if isinstance(pattern, str) else pattern
    return [l.strip() for l in text.splitlines() if l.strip() and pat.search(l)][:limit]


def _rows(ana, *kinds, limit=4):
    return [" | ".join(r["cells"]) for r in L.section_rows(ana, *kinds)][:limit]


# ---------------------------------------------------------------------------
# Clean quotes: every quote on a card is a readable line. Letter-spaced words ('P R O F I L E') are written as
# words, and a line that mixes two columns is never quoted (the resume is quoted column by column).
# ---------------------------------------------------------------------------
SPACED_NOTE = "(the PDF spaces out the letters)"
SPACED_CARDS = {"spaced_headings", "name_spacing"}
NOT_FOUND = "Not found in your resume"                  # said when something is missing: never the name or a heading
QUOTE_MAX = 240                                 # characters of one quoted line
FLAT_RE = re.compile(r"[\W_]+")


def _letter_run(tokens):
    """True for a token list that is a letter-spaced word: 4+ short tokens, most of them single letters."""
    return len(tokens) >= 4 and sum(len(t) == 1 for t in tokens) >= 0.7 * len(tokens)


def unspace_line(line, name=None):
    """'M O H A M E D  S H O K R Y' -> 'MOHAMED SHOKRY' (the readable name when it matches), 'ROWAN P R O F I L E' ->
    'ROWAN PROFILE'. Lines without letter-spaced words are returned unchanged."""
    toks = line.split()
    if not any(len(t) <= 2 for t in toks):
        return line
    if name and FLAT_RE.sub("", line).lower() == FLAT_RE.sub("", name).lower():
        return name
    out, i = [], 0
    while i < len(toks):
        j = i
        while j < len(toks) and len(toks[j]) <= 2 and re.fullmatch(r"[A-Za-z,&.\-]{1,2}", toks[j]):
            j += 1
        if _letter_run(toks[i:j]):
            run = " ".join(toks[i:j])
            fixed = Y.unspace_heading(run)
            out.append(fixed if fixed != run and not L.SPACED_RE.search(fixed) else "".join(toks[i:j]))
            i = j
        else:
            out.append(toks[i])
            i += 1
    fixed = " ".join(out)
    return fixed if fixed != " ".join(toks) else line                # no spaced word: the line as it was


def _flat(text):
    return FLAT_RE.sub(" ", text).strip().lower()


def _segments(line):
    """The parts of a quote that are text from the resume: the line, the text before a '  (note)' and what is
    inside quotation marks."""
    segs = [line, re.split(r"\s{2,}\(", line)[0]] + re.findall(r"\"([^\"]{8,})\"", line)
    return [_flat(s) for s in segs if len(s.split()) >= 3]


def mixes_columns(line, r):
    """True when the line is in the text an ATS reads (a line of two columns joined) but not in the resume read
    column by column."""
    layout = r.get("layout") or {}
    vdoc, doc = r.get("_vdoc"), r.get("_doc")
    if not (layout.get("columns_found") and vdoc and doc):
        return False
    seen = _flat(vdoc["modern"]) + " " + _flat(vdoc["strict"])
    ats = _flat(doc["modern"]) + " " + _flat(doc["strict"])
    segs = _segments(line)
    return bool(segs) and not any(s in seen for s in segs) and any(s in ats for s in segs)


def clean_quotes(lines, r, key=None):
    """The quotes of one card, readable: letter-spaced words joined, lines of mixed columns left out."""
    try:
        name = readable_name(r)[0]
    except Exception:
        name = None
    names = {_flat(n) for n in (name, (C.analyse_cv(r.get("_vdoc") or r["_doc"])["header"] or [{"text": ""}])[0]["text"])
             if n}
    words = {w for n in names for w in n.split()}
    out = []
    for l in lines:
        if not l or not l.strip():
            continue
        if _flat(l) in names or (len(_flat(l).split()) == 1 and _flat(l) in words):
            continue                                        # the name alone is never evidence
        c = Y.repair_heading(unspace_line(l, name))
        # text inside quotation marks ('Part 2 starts with: "PROFI LE"') is cleaned the same way
        c = re.sub(r'"([^"]+)"', lambda m: '"' + Y.repair_heading(unspace_line(m.group(1), name)) + '"', c)
        inner = re.findall(r'"([^"]+)"', c)
        if (_flat(c) in names or (inner and all(_flat(x) in names or _flat(x) in words for x in inner))) and key not in SPACED_CARDS:
            continue                                        # the name alone (letter spacing removed) is no evidence
        if c != l and key in SPACED_CARDS:
            c = f"{c}  {SPACED_NOTE}"
        if mixes_columns(c, r):
            continue
        if len(c) > QUOTE_MAX:                              # a joined paragraph: show the start, readable
            c = c[:QUOTE_MAX].rsplit(" ", 1)[0] + " …"
        if c not in out:
            out.append(c)
    return out


def missing_item(key, r):
    """True when the card is about something that is not in the resume at all (no visa / licence / notice period, no
    LinkedIn link, no city, no email, no headline): nothing to quote."""
    sc = r.get("structure_checks") or {}
    if key == "uae_details":
        return True
    if key == "linkedin":
        return (sc.get("T5") or {}).get("score", 1) == 0
    if key == "location":
        return (sc.get("T6") or {}).get("detail") == "no city"
    if key == "email":
        return (sc.get("T7") or {}).get("score", 1) == 0
    if key == "headline":
        return not headline_text(r)
    return False


def evidence(card, r):
    """The real CV lines that show the issue, at most a few. Problems an ATS has are quoted from the extracted
    text (what the ATS reads); content and completeness problems from the page as a person reads it."""
    key = card["key"]
    doc, v3 = r["_doc"], r["v3"]
    vdoc = r.get("_vdoc") or doc
    if (r.get("layout") or {}).get("columns_found"):
        doc = vdoc                    # columns: the ATS text is mixed; quote the clean column-by-column lines
    ana, vana = C.analyse_cv(doc), C.analyse_cv(vdoc)
    text, vtext = doc["strict"], vdoc["modern"]
    show = card.get("show") or ISSUES[key]["show"]
    own = [q for i in card["issues"] for q in i["evidence"] if q]          # quotes the CV Score already picked
    raw = C.job_lines(vana)
    job_line = lambda j: f"{raw(j)}" + (f"  ({j['problem']})" if j.get("problem") else "")
    contact = C.contact_block(vdoc)
    out = []
    if show == "quotes":
        out = own
    elif show == "spaced":
        out = L.spaced_lines(text)
    elif show == "skills_ats":
        out = _rows(ana, "skills", "competencies")
    elif show == "skills_page":
        out = _rows(vana, "skills", "competencies")
    elif show == "watermark":
        out = _lines(text, L.WATERMARK_RE)
    elif show == "header":
        out = [x["text"] for x in ana["header"][:4]]
    elif show == "contact":
        out = [x["text"] for x in vana["header"][:3]] + contact[:4]
    elif show == "markdown":
        out = _lines(text, r"\*\*")
    elif show == "html":
        out = _lines(text, L.HTML_RE)
    elif show == "placeholder":
        out = _lines(text, L.PLACEHOLDER_RE) or _lines(text, L.PLACEHOLDER_SMELL_RE)
    elif show == "glance":
        out = [" | ".join(x["cells"]) for s_ in ana["sections"] if s_["kind"] == "glance" for x in s_["rows"]] \
            or [" | ".join(x["cells"]) for x in doc["rows"] if len(x["cells"]) >= 2]
    elif show == "dates":
        bad = [j for j in vana["jobs"] if j["problem"]]
        out = [f"{j['dates']}  ({j['problem']})" if j["dates"] else job_line(j) for j in (bad or vana["jobs"])]
    elif show == "job_lines":
        out = [raw(j) for j in vana["jobs"]]
    elif show == "backticks":
        out = _lines(text, "`")
    elif show == "education":
        out = _rows(vana, "education") or _lines(vtext, "|".join(p_ for _, p_ in L.DEGREE_PATTERNS))             or _lines(vtext, EDU_HINT_RE)
    elif show == "section_names":
        out = [s_["title"] for s_ in ana["sections"] if s_["kind"] != "glance"
               and not L.is_standard_section(s_["title"])
               and not any(w in s_["title"].lower() for w in L.STANDARD_HEADING_WORDS)]
    elif show == "sections_ats":
        out = ["Sections the ATS finds: " + (", ".join(s_["title"] for s_ in ana["sections"]) or "none")]
    elif show == "sections_page":
        out = ["Sections in this resume: " + (", ".join(s_["title"] for s_ in vana["sections"]) or "none")]
    elif show == "summary":
        summ = " ".join(C.BULLET_START_RE.sub("", x["text"], count=1) for x in L.section_rows(vana, "summary"))
        out = [f"({len(summ.split())} words) {summ[:400]}{'...' if len(summ) > 400 else ''}"] if summ else []
    elif show == "template":
        reasons = (card["issues"][0].get("reasons") or []) if card["issues"] else []
        out = ["Found: " + ", ".join(reasons)] if reasons else []
        out += [q for q in own if not L.spaced_lines(q)][:2] + L.spaced_lines(vdoc["strict"])[:1]
    elif show == "page_count":                       # the page check's own sentence (its years: jobs, else dates)
        out = [e for i in card["issues"] for e in (i.get("evidence") or [])][:1]
    elif show == "length":
        pages = (r.get("layout") or {}).get("pages")
        on = f" on {pages} page{'s' if pages != 1 else ''}" if pages else ""
        out = [f"This resume has {len(vtext.split())} words{on} for about {r['experience_years']:.0f} years of "
               f"experience."]
    elif show == "skills_missing":
        required = r.get("missing_required") or []
        preferred = [t for t in r["missing_skills"] if t not in required]
        if required:                                      # with a job: what it requires, then what it prefers
            out = ["Required, not found in the resume: " + ", ".join(required)]
            out += ["Preferred, not found: " + ", ".join(preferred)] if preferred else []
        else:
            out = ["Not found in the resume: " + ", ".join(r["missing_skills"])] if r["missing_skills"] else []
    elif show == "abbreviations":
        both = lambda t: L.contains(t, vtext) and L.contains(L.other_form(t), vtext)
        used = [k["term"] for k in v3["keywords"] if L.other_form(k["term"])
                and (L.contains(k["term"], vtext) or L.contains(L.other_form(k["term"]), vtext))]
        terms = [t for t in used if not both(t)]          # a skill missing from the resume is not "one way"
        out = [l for l in vtext.splitlines() if any(L.contains(t, l) or L.contains(L.other_form(t), l)
                                                    for t in terms)][:3] or \
            [f"Written only one way: {', '.join(terms)}"] if terms else []
    out = [l.strip() for l in out if l and l.strip()]
    if missing_item(key, r):
        return [NOT_FOUND]
    lines = clean_quotes(out, r, key) or clean_quotes(own, r, key) or clean_quotes([x["text"] for x in ana["header"][:2]], r, key)
    return (lines or [NOT_FOUND])[:3]


def headline_text(r):
    """The headline the ATS finds under the name (1-2 lines, even in capitals), or None."""
    vdoc = r.get("_vdoc") or r["_doc"]
    return L.ats_fields(vdoc, C.analyse_cv(vdoc))["headline"]


def month_example(dates):
    """'2026 - Present' -> 'Jan 2026 - Present' (a month in front of every year)."""
    return re.sub(r"(?<!\w)(?:19|20)\d\d\b", lambda m: "Jan " + m.group(0), dates)


def card_text(c, r):
    """Words that depend on this resume: a headline that exists but names no role, and dates that show years only."""
    if c["key"] == "headline" and headline_text(r):
        return {"name": "Your headline does not name a target role",
                "why": "Your headline is there, but it does not say which job you are aiming for.",
                "fix": "Add your target job title to the headline, for example \"[Target title] | [Strength]\"."}
    if c["key"] == "job_details":
        t4 = r["structure_checks"]["T4"]
        if t4.get("dates_only"):
            probs = set(t4["date_problems"])
            if probs == {"year only"} and t4["date_lines"]:
                d = t4["date_lines"][0]
                return {"name": "Your job dates show years only",
                        "why": ISSUES["dates"]["why"],
                        "fix": f"Your dates show years only (e.g. {d}). Add the month: {month_example(d)}."}
            return {"name": ISSUES["dates"]["name"], "why": ISSUES["dates"]["why"], "fix": ISSUES["dates"]["fix"]}
    return {}


TITLE_WORD_RE = re.compile(r"\b(title|role|position)\b", re.I)
MISMATCH_RE = re.compile(r"\b(mismatch\w*|inconsisten\w*|misalign\w*|does not (?:match|align)|not aligned|differs?)\b", re.I)


def is_title_mismatch(i):
    """An AI finding about the job title not matching the target role ('Job title mismatch with target role',
    'Role mismatch with target position'): the same problem as the card 'The job title is not near the top'."""
    name = i.get("name") or ""
    return bool(re.search(r"\btarget\b", name, re.I) and TITLE_WORD_RE.search(name) and MISMATCH_RE.search(name))


def issue_cards(r):
    """One card per issue (internal ids grouped), sorted by points gained. -> list of dicts."""
    rank = {"Critical": 0, "Major": 1, "Minor": 2}
    cards, title_ai = {}, []
    def ai_card(i):                                   # an AI finding: its own card, in its own words
        t = ISSUES["ai_finding"]
        cards[i["id"]] = {"key": "ai_finding", "points": i["points"], "severity": i["severity"], "issues": [i],
                          "show": "quotes", "ai": True, "name": i["name"] or t["name"],
                          "why": i["ai"]["why"] or t["why"], "fix": i["ai"]["fix"] or t["fix"]}
    for i in r["issues"]:
        if i.get("ai"):
            if is_title_mismatch(i):                  # may belong to the "job title is not near the top" card
                title_ai.append(i)
            else:
                ai_card(i)
            continue
        key = ISSUE_OF.get(i["id"])
        if not key:
            continue
        c = cards.setdefault(key, {"key": key, "points": 0.0, "severity": "Minor", "issues": []})
        c["points"] = max(c["points"], i["points"])
        if rank[i["severity"]] < rank[c["severity"]]:
            c["severity"] = i["severity"]
        c["issues"].append(i)
    for i in title_ai:
        c = cards.get("job_title")
        if c is None:                                 # the job title is near the top: the AI finding stands alone
            ai_card(i)
            continue
        c["issues"].append(i)                         # ONE card: the job title does not match the job
        c["points"] = max(c["points"], i["points"])
        if rank[i["severity"]] < rank[c["severity"]]:
            c["severity"] = i["severity"]
        c["also"] = c.get("also", []) + [i["name"]]

    # C9 and C6/B9 can be two checks on the same achievement: one sees the repeated number and the other sees the
    # repeated Select Achievements text. Keep both score deductions, but show one card when the quoted evidence
    # overlaps. A repeated-text card with different evidence remains a separate card.
    numbers = cards.get("repeated_numbers")
    repeated = cards.get("repeated")
    if numbers and repeated and all(i.get("id") in {"C6", "B9"} for i in repeated["issues"]):
        def evidence_words(text):
            return set(re.findall(r"[a-z0-9$]+", (text or "").lower()))
        def result_tokens(text):
            return set(re.findall(r"(?:[$€£]\s?\d+(?:[.,]\d+)?[kmb]?|\b\d+(?:[.,]\d+)?%?|\b\d+[kmb])",
                                  (text or "").lower()))
        number_quotes = [q for i in numbers["issues"] for q in (i.get("evidence") or [])]
        repeated_quotes = [q for i in repeated["issues"] for q in (i.get("evidence") or [])]
        overlaps = any(result_tokens(a) & result_tokens(b) and len(evidence_words(a) & evidence_words(b)) >= 6
                       for a in number_quotes for b in repeated_quotes)
        if overlaps:
            numbers["points"] = round(numbers["points"] + repeated["points"], 1)
            numbers["issues"].extend(repeated["issues"])
            del cards["repeated"]
    cards = list(cards.values())
    for c in cards:
        t = ISSUES[c["key"]]
        c.update(tag=SHOWN_SEVERITY[c["severity"]], we_fix=t["we_fix"])
        if c["points"] < 0.5:                            # blocked by another part: what it adds after that is fixed
            b = max((i for i in c["issues"] if i.get("blocked_by")), key=lambda i: i["points_after"], default=None)
            if b:
                c.update(blocked_by=b["blocked_by"], points_after=b["points_after"])
        if not c.get("ai"):
            c.update(name=t["name"], why=t["why"], fix=t["fix"])
            c.update(card_text(c, r))
    return sorted(cards, key=lambda c: (-c["points"], rank[c["severity"]], c["name"]))


def compare_versions(old, new):
    """Issues fixed since the previous CV, still there, and new ones (by plain issue name)."""
    a = {c["key"]: c for c in issue_cards(old) if not c.get("ai")}     # AI findings have no fixed name
    b = {c["key"]: c for c in issue_cards(new) if not c.get("ai")}
    return {"score_before": old["score"], "score_after": new["score"],
            "fixed": [a[k]["name"] for k in a if k not in b],
            "still": [b[k]["name"] for k in b if k in a],
            "new": [b[k]["name"] for k in b if k not in a]}


OURS_MARKERS = (("career impact at a glance", 3), ("prepared with 1000jobs", 2), ("select achievements", 2))


def looks_like_1000jobs(r):
    """How strongly a resume carries the 1000Jobs layout's own marks (0 for a client's own resume): the highlight
    boxes, the "Prepared with 1000Jobs" watermark, "Select Achievements" and the ** marks are made by our generator,
    not by a client."""
    doc, vdoc = r.get("_doc") or {}, r.get("_vdoc") or r.get("_doc") or {}
    text = " ".join((x or "") for x in (doc.get("modern"), doc.get("strict"), vdoc.get("modern"), vdoc.get("strict")))
    text = " ".join(text.lower().split())
    score = sum(weight for marker, weight in OURS_MARKERS if marker in text)
    score += 1 if "**" in text else 0
    score += 2 if any(i.get("id") == "B8" for i in r.get("issues") or []) else 0    # the highlight boxes, by layout
    return score


OURS_MARK_WORDS = ("career impact at a glance", "select achievements", "prepared with 1000jobs")
OURS_MARK_LABELS = {"career impact at a glance": "a \"Career Impact at a Glance\" section",
                    "select achievements": "a \"Select Achievements\" section",
                    "prepared with 1000jobs": "the \"Prepared with 1000Jobs\" watermark",
                    "** marks": "** formatting marks", "name": "its file name (Name_Company)"}


def pdf_head_text(data, pages=2):
    """The readable text of the first pages of an uploaded PDF (bytes): for the light checks made before a check
    runs. A file we cannot read gives "": the check itself says what is wrong with it."""
    import io

    import pdfplumber
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            return "\n".join((p.extract_text(x_tolerance=3) or "") for p in pdf.pages[:pages])
    except Exception:
        return ""


def name_looks_like_ours(file_name):
    """The generator names its files Name_Company.pdf (the user's own are usually Name_CV.pdf): True when the name has
    two or more underscores and does not say CV or resume."""
    stem = os.path.splitext(os.path.basename(file_name or ""))[0].lower()
    return stem.count("_") >= 2 and not re.search(r"\b(cv|resume|curriculum)\b", stem.replace("_", " "))


def template_marks(data, file_name=""):
    """Which 1000Jobs marks a resume shows, read from its text without scoring anything (the layout's own words and
    ** marks), plus its file name. -> a list of short labels, empty for a user's own resume."""
    text = pdf_head_text(data)
    flat = " ".join(text.lower().split())
    found = [OURS_MARK_LABELS[m] for m in OURS_MARK_WORDS if m in flat]
    if "**" in text:
        found.append(OURS_MARK_LABELS["** marks"])
    if name_looks_like_ours(file_name):
        found.append(OURS_MARK_LABELS["name"])
    return found


def client_pair(main, previous, swap=None):
    """(the client's original resume, our 1000Jobs resume, were they uploaded the other way round?).

    `main` is the file in the 1000Jobs slot and `previous` the file in the user's own resume slot. `swap` is what the
    team said with the Swap button: True = the two files came the other way round, None = they did not say. When they
    did not say, the roles are decided by the 1000Jobs marks a file carries, never by the upload slot alone: a file
    with the highlight boxes, the watermark or the ** marks is ours, so the report can never describe our own resume
    as the client's original (the Sana case). When neither file carries them, or both do (an old 1000Jobs version next
    to a new one), the slots are kept as they are."""
    if swap is not None:
        return (main, previous, True) if swap else (previous, main, False)
    ours_main, ours_previous = looks_like_1000jobs(main), looks_like_1000jobs(previous)
    if ours_previous >= 3 and ours_previous > ours_main:      # the 1000Jobs resume came in as the "previous" one
        return main, previous, True
    return previous, main, False


def client_comparison(old, new):
    """The client comparison report for a pair whose roles are already known (see client_pair): `old` is the client's
    original resume, `new` our 1000Jobs resume. Of `new` only its scores are used (and which issues it no longer has);
    every problem shown comes from `old`.
    -> {"old", "new", "parts": [(part, old, new)], "improved": [cards of old], "issues": [cards of old]}"""
    old_cards = issue_cards(old)
    still = {c["key"] for c in issue_cards(new) if not c.get("ai")}
    improved = [c for c in old_cards if not c.get("ai") and c["key"] not in still]   # an AI finding has no fixed name
    parts = [p for p in PART_NAMES if p in old["parts"] and p in new["parts"]]
    return {"old": old["score"], "new": new["score"], "parts": [(p, old["parts"][p], new["parts"][p]) for p in parts],
            "improved": improved, "issues": old_cards}


def quote_key(text):
    """Text ready to be compared with a resume's own text: letters and digits only, in lower case. Line breaks,
    letter spacing, dashes, bullets and quotation marks do not matter then ("2019 - 2023" = "2019–2023")."""
    return re.sub(r"[^0-9a-z]+", "", text.lower())


def own_text(r):
    """The resume's own text as one comparison key (its modern and its strict extraction): what a quote of this
    resume must be found in."""
    doc, vdoc = r.get("_doc") or {}, r.get("_vdoc") or r.get("_doc") or {}
    text = " ".join((x or "") for x in (doc.get("modern"), doc.get("strict"), vdoc.get("modern"), vdoc.get("strict")))
    return quote_key(text)


def from_other_only(line, r, other):
    """True when the line is text of the other resume and not of `r`: such a line is never shown as a quote of `r`.
    A line we wrote ourselves ("Not found in your resume") has no resume text: it is kept."""
    segs = _segments(line) if other is not None else []
    if not segs:
        return False
    mine, theirs = own_text(r), own_text(other)
    return not any(quote_key(s) in mine for s in segs) and any(quote_key(s) in theirs for s in segs)


def short_quote(c, r, other=None):
    """A short quote of the card's problem in resume `r`: its first lines, each cut to a readable length. With
    `other` (the 1000Jobs resume in the client report), a line that is the other resume's own text is left out, so a
    "Before" quote always comes from the resume it is presented as."""
    lines = [l for l in before_after(c, r)[1] if not l.startswith("←")]
    lines = [l for l in lines if not from_other_only(l, r, other)][:MAX_QUOTE_LINES]
    return [l if len(l) <= MAX_QUOTE_CHARS else l[:MAX_QUOTE_CHARS - 1].rstrip() + "…" for l in lines] \
        or [REPORT_TEXT["nothing_shown"]]


# ---------------------------------------------------------------------------
# Look and feel: ONE stylesheet for the page and the downloadable report
# ---------------------------------------------------------------------------
REPORT_CSS = """
.rp {font-family: "Plus Jakarta Sans", "Segoe UI", system-ui, -apple-system, Roboto, Arial, sans-serif;
  color: #0f172a; line-height: 1.45;}
.rp * {box-sizing: border-box;}
.rp .card {background: #fff; border: 1px solid #e2e8f0; border-radius: 16px; padding: 20px 22px; margin: 0 0 16px 0;
  box-shadow: 0 1px 3px rgba(15,23,42,0.05); overflow-wrap: anywhere;}
.rp .rh {margin: 0 0 16px 0; padding: 0 0 14px 0; border-bottom: 2px solid #e2e8f0;}
.rp .rh-top {display: flex; align-items: center; gap: 12px; margin-bottom: 12px;}
.rp .rh h1 {margin: 0; font-size: 1.45rem; font-weight: 800; letter-spacing: -0.3px; color: #0f172a;}
.rp .rh-meta {display: flex; flex-wrap: wrap; gap: 8px 28px; margin: 0;}
.rp .rm {margin: 0; min-width: 0;} .rp .rm dt {color: #64748b; font-size: 0.72rem; font-weight: 700;
  text-transform: uppercase; letter-spacing: 0.5px;} .rp .rm dd {margin: 1px 0 0 0; font-size: 0.92rem; font-weight: 600;
  overflow-wrap: anywhere;}
.rp .vers {margin: 0 0 14px 0; font-size: 0.9rem;}
.rp .plain {border-top: 1px solid #e2e8f0; margin-top: 14px; padding-top: 10px; color: #475569; font-size: 0.9rem;}
.rp .hdr {display: flex; flex-wrap: wrap; align-items: center; gap: 10px 14px; margin-bottom: 16px;}
.rp .logo {width: 36px; height: 36px; border-radius: 9px; background: #0f172a; color: #fff; font-weight: 800;
  display: flex; align-items: center; justify-content: center; font-size: 0.9rem; flex: 0 0 auto;}
.rp .app {font-weight: 700; font-size: 1.05rem;} .rp .app span {color: #2563eb;}
.rp .tag {color: #64748b; font-size: 0.8rem;}
.rp .grow {flex: 1 1 auto;}
.rp .pill {display: inline-block; border: 1px solid #e2e8f0; border-radius: 10px; padding: 5px 12px; font-size: 0.85rem;
  background: #fff; color: #0f172a;}
.rp .pill .sz {color: #64748b; margin-left: 6px;}
.rp .switch {display: inline-flex; border: 1px solid #e2e8f0; border-radius: 10px; padding: 3px; background: #f1f5f9;}
.rp .switch span {padding: 3px 10px; border-radius: 7px; font-size: 0.82rem; color: #64748b;}
.rp .switch span.on {background: #fff; color: #0f172a; font-weight: 600; box-shadow: 0 1px 2px rgba(15,23,42,0.1);}
.rp .score {display: flex; flex-wrap: wrap; gap: 18px 28px; align-items: center;}
.rp .ring {flex: 0 0 auto; text-align: center;}
.rp .ring .of {color: #64748b; font-size: 0.8rem; margin-top: -6px;}
.rp .sbody {flex: 1 1 320px; min-width: 0;}
.rp .lbl {display: inline-block; padding: 3px 12px; border-radius: 999px; font-weight: 600; font-size: 0.82rem;
  margin-right: 8px;}
.rp .muted {color: #64748b; font-size: 0.85rem;}
.rp .big {font-size: 1.6rem; font-weight: 800; letter-spacing: -0.3px; margin: 8px 0 6px 0; line-height: 1.25;}
.rp .big b {color: #b45309;}
.rp .lead {color: #475569; margin: 0 0 12px 0;}
.rp .bar {position: relative; height: 10px; border-radius: 999px; background: #eef2f7; overflow: hidden; margin: 4px 0 2px 0;}
.rp .bar i {position: absolute; left: 0; top: 0; bottom: 0; border-radius: 999px;}
.rp .barlbl {display: flex; justify-content: space-between; font-size: 0.8rem; color: #475569;}
.rp .barlbl .aft {color: #b45309;}
.rp .counts {display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px;}
.rp .count {display: inline-block; white-space: nowrap; border: 1px solid #e2e8f0; border-radius: 10px;
  padding: 5px 12px; font-size: 0.85rem; line-height: 1.5; color: #475569;}
.rp .nw {white-space: nowrap;}
.rp .count b {color: #0f172a; font-size: 1rem; margin-right: 5px;}
.rp .count.c-imp b {color: #b45309;} .rp .count.c-crit b {color: #dc2626;} .rp .count.c-gain b {color: #16a34a;}
.rp .note {color: #92400e; background: #fef3c7; border-radius: 8px; padding: 6px 10px; font-size: 0.85rem; margin-top: 10px;}
.rp .parts {display: flex; flex-wrap: wrap; gap: 14px; margin-bottom: 16px;}
.rp .part {flex: 1 1 220px; min-width: 0; position: relative; margin: 0; padding-top: 22px;}
.rp .part.best {border: 2px solid #f59e0b;}
.rp .best-tag {position: absolute; top: -11px; left: 18px; background: #f59e0b; color: #fff; font-size: 0.7rem;
  font-weight: 700; letter-spacing: 0.4px; padding: 2px 10px; border-radius: 999px; text-transform: uppercase;}
.rp .ph {display: flex; justify-content: space-between; align-items: baseline; gap: 8px;}
.rp .ph .n {font-weight: 700;} .rp .ph .v {font-size: 1.7rem; font-weight: 800;}
.rp .scale {color: #94a3b8; font-size: 0.72rem; margin: 6px 0 4px 0;}
.rp .ok {color: #166534; font-size: 0.86rem; margin: 4px 0;}
.rp .ok:before {content: "\\2713"; font-weight: 700; margin-right: 8px;}
.rp .sep {border-top: 1px solid #eef2f7; margin: 8px 0;}
.rp .row {display: flex; justify-content: space-between; gap: 10px; font-size: 0.86rem; margin: 5px 0;}
.rp .row .nm {min-width: 0;}
.rp .row .pt {flex: 0 0 auto; text-align: right; white-space: nowrap;}
.rp .row .pt b {color: #dc2626;} .rp .row .pt span {color: #16a34a; font-size: 0.75rem; margin-left: 6px;}
.rp .row.small {color: #64748b;}
.rp .blk {color: #92400e; font-size: 0.8rem; margin-top: 8px;}
.rp h2 {font-size: 1.35rem; font-weight: 800; margin: 22px 0 2px 0; padding: 0;}
.rp .sub {color: #64748b; font-size: 0.86rem; margin-bottom: 12px;}
.rp details.iss {background: #fff; border: 1px solid #e2e8f0; border-radius: 14px; margin: 0 0 10px 0;}
.rp details.iss > summary {list-style: none; cursor: pointer; display: flex; align-items: center; gap: 12px;
  padding: 14px 16px;}
.rp details.iss > summary::-webkit-details-marker {display: none;}
.rp .num {flex: 0 0 auto; width: 28px; height: 28px; border-radius: 8px; background: #f1f5f9; color: #334155;
  display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 0.85rem;}
.rp .num.Important {background: #fef3c7; color: #92400e;} .rp .num.Critical {background: #fee2e2; color: #991b1b;}
.rp .it {flex: 1 1 auto; min-width: 0;}
.rp .it .t {font-weight: 650; font-weight: 600;} .rp .it .m {color: #64748b; font-size: 0.8rem;}
.rp .gain {flex: 0 0 auto; background: #dcfce7; color: #166534; font-weight: 700; font-size: 0.8rem;
  padding: 3px 10px; border-radius: 999px; white-space: nowrap;}
.rp .gain.wait {background: #f1f5f9; color: #64748b; font-weight: 600;}
.rp details.iss > summary:after {content: "\\203A"; transform: rotate(90deg); color: #94a3b8; font-size: 1.3rem;
  flex: 0 0 auto; line-height: 1;}
.rp details.iss[open] > summary:after {transform: rotate(-90deg);}
.rp .ib {padding: 0 16px 16px 16px; border-top: 1px solid #eef2f7;}
.rp .ba {display: flex; flex-wrap: wrap; gap: 14px; margin-top: 14px;}
.rp .ba > div {flex: 1 1 260px; min-width: 0;}
.rp .cap {font-size: 0.7rem; font-weight: 700; letter-spacing: 0.5px; color: #64748b; text-transform: uppercase;
  margin-bottom: 6px;}
.rp .code {border-radius: 10px; padding: 10px 12px; font-family: Consolas, "Courier New", monospace; font-size: 0.8rem;
  white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.5;}
.rp .code.now {background: #0f172a; color: #e2e8f0;}
.rp .code.aft {background: #f0fdf4; color: #14532d; border: 1px solid #bbf7d0;}
.rp .code .new {display: block; background: #dcfce7; border-radius: 4px; padding: 0 4px;}
.rp .code .gone {display: block; color: #fbbf24;}
.rp .wf {display: flex; flex-wrap: wrap; gap: 12px; margin-top: 12px;}
.rp .wf > div {flex: 1 1 260px; min-width: 0; background: #f8fafc; border-radius: 10px; padding: 10px 12px;
  font-size: 0.86rem; color: #334155;}
.rp .wf b {display: block; color: #0f172a; margin-bottom: 2px;}
.rp .also {color: #64748b; font-size: 0.8rem; margin-top: 8px;}
.rp details.more > summary {list-style: none; cursor: pointer; text-align: center; margin: 4px auto 14px auto;
  border: 1px solid #e2e8f0; border-radius: 10px; padding: 7px 16px; width: max-content; max-width: 100%;
  background: #fff; font-size: 0.86rem;}
.rp details.more > summary::-webkit-details-marker {display: none;}
.rp details.more[open] > summary {display: none;}
.rp .imp {display: flex; flex-wrap: wrap; gap: 16px; margin-top: 18px;}
.rp .imp > .card {flex: 1 1 300px; min-width: 0; margin: 0;}
.rp .imp .why {background: #0f172a; color: #fff; border-color: #0f172a;}
.rp .imp h3 {font-size: 1.15rem; font-weight: 800; margin: 0 0 2px 0;}
.rp .fx {display: flex; gap: 12px; align-items: flex-start; border: 1px solid #e2e8f0; border-radius: 12px;
  padding: 10px 12px; margin-top: 10px;}
.rp .fx .d {flex: 0 0 auto; width: 24px; height: 24px; border-radius: 999px; background: #1d4ed8; color: #fff;
  font-size: 0.78rem; font-weight: 700; display: flex; align-items: center; justify-content: center;}
.rp .fx .x {flex: 1 1 auto; min-width: 0;} .rp .fx .x b {display: block; font-size: 0.9rem;}
.rp .fx .x span {color: #64748b; font-size: 0.8rem;}
.rp .fx .p {flex: 0 0 auto; color: #16a34a; font-weight: 700; font-size: 0.85rem;}
.rp .wl {display: flex; gap: 10px; margin-top: 12px; font-size: 0.92rem;}
.rp .wl i {flex: 0 0 auto; width: 20px; height: 20px; border-radius: 5px; background: #1e40af; color: #fff;
  font-style: normal; font-size: 0.75rem; display: flex; align-items: center; justify-content: center;}
.rp .chip {display: inline-block; padding: 4px 12px; margin: 3px 4px 3px 0; border-radius: 999px;
  background: #eef2ff; color: #3730a3; font-size: 0.85rem;}
.rp .chip.req {background: #fee2e2; color: #991b1b;}
"""
# the client comparison report only (page and PDF); the normal report does not use it
CLIENT_CSS = """
.rp .cmp {display: flex; flex-wrap: wrap; gap: 14px; margin-bottom: 14px;}
.rp .cmp > div {flex: 1 1 240px; min-width: 0; display: flex; align-items: center; gap: 14px; border: 1px solid #e2e8f0;
  border-radius: 14px; padding: 12px 14px;}
.rp .cmp > div.ours {border: 2px solid #1d4ed8;}
.rp .cmp .who {font-size: 1.1rem; font-weight: 800;} .rp .cmp .chg {color: #16a34a; font-weight: 700;}
.rp .cmp .file {color: #64748b; font-size: 0.78rem; word-break: break-word;}
.rp .cmp .chg.down {color: #dc2626;}
.rp table.pt {width: 100%; border-collapse: collapse; font-size: 0.9rem;}
.rp table.pt th {text-align: left; color: #64748b; font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.5px;
  font-weight: 700; padding: 6px 8px; border-bottom: 1px solid #e2e8f0;}
.rp table.pt td {padding: 7px 8px; border-bottom: 1px solid #eef2f7;}
.rp table.pt th + th, .rp table.pt td + td {text-align: right; white-space: nowrap;}
.rp .imv {display: flex; gap: 12px; align-items: flex-start; border: 1px solid #e2e8f0; border-radius: 12px;
  padding: 12px 14px; margin-top: 10px; background: #fff;}
.rp .imv > i {flex: 0 0 auto; width: 24px; height: 24px; border-radius: 999px; background: #16a34a; color: #fff;
  font-style: normal; font-size: 0.8rem; display: flex; align-items: center; justify-content: center;}
.rp .imv > div {flex: 1 1 auto; min-width: 0;} .rp .imv .t {font-weight: 600; margin-bottom: 6px;}
.rp .imv .code {padding: 6px 10px; margin-bottom: 6px;}
.rp .imv .chd {font-size: 0.86rem; color: #334155;} .rp .imv .chd b {color: #166534;}
.rp .ci {background: #fff; border: 1px solid #e2e8f0; border-radius: 14px; margin: 0 0 10px 0;}
.rp .ci > .hd {display: flex; align-items: center; gap: 12px; padding: 14px 16px 10px 16px;}
.rp .ci .ib {border-top: 1px solid #eef2f7;}
@media print {.rp .imv, .rp .ci {break-inside: avoid; page-break-inside: avoid;}}
"""
# the downloadable report: same look, every issue open, nothing cut or overlapping on paper
PRINT_CSS = """
body {background: #f3f5f9; margin: 0; padding: 24px;}
.rp {max-width: 960px; margin: 0 auto;}
@page {size: A4; margin: 12mm;}
@media print {
  body {background: #fff; padding: 0;}
  .rp {max-width: none;}
  .rp * {-webkit-print-color-adjust: exact; print-color-adjust: exact;}
  .rp .card, .rp details.iss, .rp .fx, .rp .wf > div, .rp .ba > div {break-inside: avoid;
    page-break-inside: avoid;}
  .rp .parts {padding-top: 12px;}
  .rp .part {break-inside: avoid; page-break-inside: avoid;}
  .rp .card, .rp details.iss {box-shadow: none;}
  .rp h2 {break-after: avoid; page-break-after: avoid;}
  .rp .keep {break-inside: avoid; page-break-inside: avoid;}
  .rp details.iss > summary:after {display: none;}
  .rp details.more > summary {display: none;}
}
"""
# Streamlit's own containers
FONT_URL = "https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap"
BLUE, BLUE_DARK = "#1d4ed8", "#1e40af"
PAGE_CSS = """
.stApp {background: #f4f6fa;}
.stApp p, .stApp label, .stApp button, .stApp input, .stApp textarea, .stApp li, .stApp h1, .stApp h2, .stApp h3,
.stApp [data-testid="stMarkdownContainer"], .stApp [data-testid="stCaptionContainer"] {
  font-family: "Plus Jakarta Sans", "Segoe UI", system-ui, -apple-system, Roboto, Arial, sans-serif;}
header[data-testid="stHeader"] {display: none;}
.block-container {max-width: 1080px; padding-top: 0 !important; padding-bottom: 3rem;}
div[data-testid="stVerticalBlockBorderWrapper"] {border-radius: 16px;}

/* the slim top bar: white, across the whole page, thin bottom border */
.st-key-atsl-topbar {background: #fff; padding: 10px 0; margin-bottom: 12px;
  box-shadow: 0 0 0 100vmax #fff, 0 1px 0 100vmax #e2e8f0; clip-path: inset(0 -100vmax -1px -100vmax);}
.stApp [data-testid="stElementContainer"]:has(> div > div > style),
.stApp [data-testid="stElementContainer"]:has(style:only-child) {display: none;}
[data-testid="stMainBlockContainer"] {padding-top: 0 !important;}
.st-key-atsl-topbar [data-testid="stHorizontalBlock"] {gap: 12px;}
.atsl-brand {display: flex; align-items: center; gap: 12px; min-width: 0;}
.atsl-brand .logo {width: 36px; height: 36px; border-radius: 9px; background: #0f172a; color: #fff; font-weight: 800;
  display: flex; align-items: center; justify-content: center; font-size: 0.85rem; flex: 0 0 auto;}
.atsl-brand .app {font-weight: 700; font-size: 1rem; color: #0f172a; line-height: 1.2; white-space: nowrap;}
.atsl-brand .app span {color: #2563eb;}
.atsl-brand .tag {color: #64748b; font-size: 0.78rem; white-space: nowrap;}
.atsl-chip {display: flex; align-items: center; gap: 8px; border: 1px solid #e2e8f0; border-radius: 10px;
  padding: 6px 12px; font-size: 0.84rem; color: #0f172a; background: #fff; min-width: 0; margin-left: auto;
  width: max-content; max-width: 100%;}
.atsl-chip svg {flex: 0 0 auto;}
.atsl-chip .nm {overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0;}
.atsl-chip .sz {color: #64748b; white-space: nowrap; flex: 0 0 auto;}

/* the With / Without switch: a pill, the selected side white */
.st-key-atsl-topbar div[role="radiogroup"] {background: #f1f5f9; border: 1px solid #e2e8f0; border-radius: 10px;
  padding: 3px; gap: 0; flex-wrap: nowrap; width: max-content; margin-left: auto;}
.st-key-atsl-topbar div[role="radiogroup"] label {margin: 0; padding: 4px 12px; border-radius: 7px; cursor: pointer;
  white-space: nowrap;}
.st-key-atsl-topbar div[role="radiogroup"] label > div:first-child {display: none;}
.st-key-atsl-topbar div[role="radiogroup"] label > div:last-child {padding-left: 0;}
.st-key-atsl-topbar div[role="radiogroup"] label p {font-size: 0.82rem; color: #64748b;}
.st-key-atsl-topbar div[role="radiogroup"] label:has(input:checked) {background: #fff;
  box-shadow: 0 1px 2px rgba(15,23,42,0.12);}
.st-key-atsl-topbar div[role="radiogroup"] label:has(input:checked) p {color: #0f172a; font-weight: 600;}
.st-key-atsl-topbar .stRadio {margin-bottom: 0;}

/* buttons: the design's blue (no red anywhere) */
.stApp button[kind="primary"], .stApp [data-testid="stBaseButton-primary"] {background: BLUE; border: 1px solid BLUE;
  color: #fff; border-radius: 10px; font-weight: 600;}
.stApp button[kind="primary"]:hover, .stApp [data-testid="stBaseButton-primary"]:hover {background: BLUE_DARK;
  border-color: BLUE_DARK; color: #fff;}
.stApp button[kind="secondary"], .stApp [data-testid="stBaseButton-secondary"] {border-radius: 10px;
  border-color: #e2e8f0; font-weight: 600;}
.stApp button[kind="secondary"]:hover, .stApp [data-testid="stBaseButton-secondary"]:hover {border-color: BLUE;
  color: BLUE;}
.st-key-atsl-topbar button {white-space: nowrap;}
.st-key-atsl-topbar [data-testid="stColumn"]:last-child [data-testid="stVerticalBlock"] {align-items: flex-end;}
.st-key-atsl-topbar [data-testid="stColumn"]:last-child [data-testid="stElementContainer"] {width: auto !important;
  margin-left: auto;}

/* the upload card */
.st-key-atsl-upload {background: #fff; border: 1px solid #e2e8f0; border-radius: 16px; padding: 20px 22px;
  box-shadow: 0 1px 3px rgba(15,23,42,0.05);}
.st-key-atsl-upload h3 {font-size: 1.15rem; font-weight: 800; margin: 0; padding: 0;}
""".replace("BLUE_DARK", BLUE_DARK).replace("BLUE", BLUE)
CSS = f'<style>@import url("{FONT_URL}");' + PAGE_CSS + REPORT_CSS + "</style>"

# every text of the report page, in one place
REPORT_TEXT = {
    "app": "1000Jobs <span>ATS Lab</span>", "tagline": "Resume Score, problems and fixes",
    "with": "With job description", "without": "Without",
    "who": "{name}'s resume", "who_unknown": "This resume",
    "headline": "{who} can reach about <b>{after}</b> by fixing {n} issue{s}.",
    "headline_rebuild": "{who} can reach about <b>{after}</b> after moving to a single-column, portrait resume{more}.",
    "rebuild_more": " and fixing {n} more issue{s}",
    "headline_none": "{who} meets the 1000Jobs resume standard.",
    "read_well": "It reads well in an ATS.", "read_ok": "An ATS can read most of it.",
    "read_bad": "An ATS has trouble reading it.",
    "most_lost": "Most points are lost in <b>{part}</b>: {issues}.",
    "checked_job": "Checked against the job: {target}", "checked_std": "Checked against the 1000Jobs resume standard",
    "now": "Now {now}", "after": "After top fixes: about {after}",
    "found": "issues found", "important": "important", "critical": "critical",
    "available": "points from the top {n} fix{es}",
    "held": "The score is held at 70 because no bullet shows a number or result.",
    "out_of": "out of 100", "biggest": "Biggest gain",
    "scale": "points lost in {part} · +gain on your Resume Score",
    "smaller": "Other issues", "perfect": "Nothing lowered this part.",
    "top": "Top issues",
    "top_sub": "Sorted by points gained on your Resume Score (+pts). Open any issue to see what the ATS reads and "
               "how to fix it.",
    "more": "Show {n} more issue{s}", "no_issues": "No issues found. Well done!",
    "now_ats": "What the ATS reads now", "now_page": "In your resume now", "after_fix": "After the fix",
    "why_hurts": "Why it hurts", "how_fix": "How to fix it", "also": "Also covers: {names}",
    "part_cost": "−{p} {part} points", "ai": "AI suggestion", "ai_ok": "AI suggestion, confirmed by the Lab",
    "nothing_shown": "Nothing to show: this part is missing from the resume.",
    "download": "Download PDF", "download_html": "Download HTML report", "fixes": "Fixes: {issue}",
    "report_title": "1000Jobs ATS Lab - Resume Report", "candidate": "Candidate", "file": "Resume file",
    "date": "Date", "checked": "Checked", "no_name": "Not found in the resume",
    "without_job_plain": "Without a job description", "with_job_plain": "With a job description",
    "job_title": "Target role",
    "job_title_label": "Target role (job title)", "job_title_hint": "e.g. Brand Marketing Manager",
    "job_title_help": "Required with a job description. The title of the job you are applying for: it is used for "
                      "the job title and headline checks.",
    "plain": "This resume scored {score} out of 100: the score shows how easily the software that companies use to "
             "screen resumes (an ATS) can read it, and how well it meets the 1000Jobs resume standard.",
    "plain_job": "This resume scored {score} out of 100: the score shows how easily an ATS can read this resume, how "
                 "well it meets the 1000Jobs standard, and how well it matches this job.",
    "pdf_preparing": "Preparing the PDF...",
    "pdf_failed": "The PDF could not be created on this computer ({why}). You can download the HTML report instead: "
                  "it opens in any browser and can be printed or saved as a PDF from there.",
    "new": "Check new resume", "upload_title": "Check a resume",
    "upload_sub": "Upload a PDF. Add the job description to see how well it matches the job.",
    "std_note": "The resume is checked against the 1000Jobs resume standard: readability, content and structure.",
    "again_job": "Paste the job description to check this resume against the job.",
    "again_std": "Check this resume again without the job description.", "again": "Check again",
}
# 'What the ATS reads now' only for problems in the text an ATS extracts; the rest is the resume as people read it
ATS_SHOWS = {"spaced", "skills_ats", "watermark", "header", "markdown", "html", "placeholder", "glance", "backticks",
             "sections_ats"}
STANDARD_NAMES = [("experience", "Experience"), ("employment", "Experience"), ("education", "Education"),
                  ("skill", "Skills"), ("competenc", "Skills"), ("certif", "Certifications"),
                  ("language", "Languages"), ("summary", "Summary"), ("profile", "Summary")]
MONTH_END_RE = re.compile(r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s*$", re.I)


def month_placeholders(line):
    """'Lead 2019 - 2020' -> 'Lead [Mon] 2019 - [Mon] 2020' (a year that already has its month is kept)."""
    return re.sub(r"(?<!\w)(?:19|20)\d\d\b",
                  lambda m: m.group(0) if MONTH_END_RE.search(line[:m.start()]) else "[Mon] " + m.group(0), line)
PHONE_IN_RE = re.compile(r"\(?\+?\(?\d[\d\s().-]{7,}\d")


def esc(text):
    """HTML-escaped text for the report ($ escaped too, so Streamlit never reads it as math)."""
    return html.escape(str(text)).replace("$", "&#36;").replace("\n", "<br>")


def fmt(p):
    """Points as shown: whole numbers from 1 up, one decimal below."""
    p = round(float(p), 1)
    return f"{round(p):d}" if abs(p) >= 1 else f"{p:g}"


def color_for(score):
    return "#16a34a" if score >= 70 else "#f59e0b" if score >= 40 else "#dc2626"


LABEL_COLORS = {"Excellent": ("#dcfce7", "#166534"), "Strong": ("#dcfce7", "#166534"), "Good": ("#e0f2fe", "#075985"),
                "Needs work": ("#fef3c7", "#92400e"), "At risk": ("#ffedd5", "#9a3412"),
                "Not ready": ("#fee2e2", "#991b1b")}


def gauge(score, size, caption="", label=""):
    """A circle gauge (SVG): the score inside, colored green / orange / red."""
    r, stroke = size / 2 - 10, 14 if size > 150 else 8
    circ = 2 * 3.14159 * r
    filled = circ * max(0.0, min(100.0, score)) / 100
    col = color_for(score)
    return (f'<div class="atsl-gauge"><svg width="{size}" height="{size}" viewBox="0 0 {size} {size}">'
            f'<circle cx="{size/2}" cy="{size/2}" r="{r}" fill="none" stroke="#eef2f7" stroke-width="{stroke}"/>'
            f'<circle cx="{size/2}" cy="{size/2}" r="{r}" fill="none" stroke="{col}" stroke-width="{stroke}" '
            f'stroke-linecap="round" stroke-dasharray="{filled:.1f} {circ:.1f}" '
            f'transform="rotate(-90 {size/2} {size/2})"/>'
            f'<text x="50%" y="50%" text-anchor="middle" dominant-baseline="central" font-size="{size * 0.28:.0f}" '
            f'font-weight="800" fill="#0f172a">{round(score)}</text></svg>'
            + (f'<div class="lbl" style="color:{col}">{html.escape(label)}</div>' if label else "")
            + (f'<div class="cap">{html.escape(caption)}</div>' if caption else "") + "</div>")


def chips(words, cls=""):
    return "".join(f'<span class="chip {cls}">{esc(w)}</span>' for w in words)


# ---------------------------------------------------------------------------
# What the report says (no Streamlit: tested directly)
# ---------------------------------------------------------------------------
def lower_first(text):
    return text[:1].lower() + text[1:] if text[1:2].islower() or len(text) < 2 else text


NOT_NAME_RE = re.compile(r"\b(experience|education|skills?|summary|profile|contact|resume|curriculum|vitae|cv)\b",
                         re.I)


def looks_like_name(text):
    """'Tareq Al Masri', 'MOHAMED SHOKRY, MBA', 'SANA MALIK, PMP®', 'Dr. Jane Doe', 'M O H A M E D' - not a heading
    ('Work Experience'), a job title, contact details or a sentence. Titles and credentials are not counted."""
    t = L.NAME_MARKS_RE.sub("", text or "").strip()
    flat = re.sub(r"(?<=\S) (?=\S(?: |$))", "", t) if L.spaced_lines(t) else t
    words = [w for w in re.split(r"[\s,]+", L.bare_name(flat)) if w]
    return bool(words) and not re.search(r"[@\d|:/]", t) and len(words) <= 6 and not NOT_NAME_RE.search(flat) \
        and not L.TITLE_WORDS.search(flat) and all(re.fullmatch(r"[A-Za-z][A-Za-z'.-]*", w) for w in words)


def readable_name(r):
    """(full name in normal letters, first name) from the ATS name field. A letter-spaced name
    ('M O H A M E D S H O K R Y') is the line read again from its letters (r["name_line"]: the PDF's own word
    spaces); else it is put back together with the words of the file name when they match; otherwise (None, None):
    the report says 'This resume'."""
    head = C.analyse_cv(r.get("_vdoc") or r["_doc"])["header"]
    names = [head[0]["text"] if head else "", r["v3"]["ats_view"]["fields"].get("name") or ""]
    names += [re.split(r"\s+(?=\S*@|\+?\(?\d)", n)[0] for n in names]    # 'Shikha Sureka shikha@mail.com +971 ...'
    name = next((n.strip() for n in names if looks_like_name(n)), "")
    if not name:
        return None, None
    line = r.get("name_line")
    if line and L.spaced_lines(name) and not L.spaced_lines(line) and looks_like_name(line):
        name = line
    if re.fullmatch(r"(?:\S\s){3,}\S.*", name) and L.spaced_lines(name):
        flat = re.sub(r"\s+", "", name)
        words, pos = [], 0
        stem = os.path.splitext(os.path.basename(r.get("cv") or ""))[0]
        for tok in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])", stem):
            if len(tok) >= 2 and flat[pos:].lower().startswith(tok.lower()):
                words.append(flat[pos:pos + len(tok)])
                pos += len(tok)
        if not words:
            return None, None
        rest = flat[pos:]
        full = re.sub(r"\s*,\s*", ", ", " ".join(words) + (rest if rest[:1] == "," else " " + rest)).strip()
        return full, words[0].title()
    first = re.split(r"[\s,|]+", L.bare_name(name))[0]           # never 'Dr.'
    if not re.fullmatch(r"[A-Za-z][A-Za-z'.-]+", first):
        return name, None
    return name, first.title() if first.isupper() or first.islower() else first


def top_cards(cards):
    """The fixes the summary counts: the first TOP_CARDS cards that add points (now, or once a blocker is fixed)."""
    return [c for c in cards if c["points"] > 0 or c.get("points_after")][:TOP_CARDS]


def headline_sentence(s, who):
    """'... can reach about X by fixing N issues', or, when the layout must be rebuilt (rule 5): '... can reach about X
    after moving to a single-column, portrait resume and fixing N more issues'."""
    if not s["n_fix"]:
        return REPORT_TEXT["headline_none"].format(who=who)
    if s["rebuild"]:
        n = s["n_fix"] - s["n_layout"]
        more = REPORT_TEXT["rebuild_more"].format(n=n, s="s" if n != 1 else "") if n > 0 else ""
        return REPORT_TEXT["headline_rebuild"].format(who=who, after=fmt(s["after"]), more=more)
    return REPORT_TEXT["headline"].format(who=who, after=fmt(s["after"]), n=s["n_fix"], s="s" if s["n_fix"] != 1 else "")


LAYOUT_CARDS = {"template", "page_format", "image_page", "sidebar", "columns", "reading_order"}


def report_summary(r, cards):
    """The score card's numbers, all from the scorer: the score with the top fixes applied TOGETHER
    (r["_score_with"]), counts of the cards on this page, and the part with the most points to recover."""
    top = top_cards(cards)
    now = r["score"]
    after = r["_score_with"]([i["id"] for c in top for i in c["issues"]]) if top else now
    after = max(now, min(MAX_PROMISE, after))         # a resume can always improve: never promise more than 95
    gain = {p: r["_score_with"]([i["id"] for i in r["issues"] if i["part"] == p]) - now for p in r["parts"]}
    best = max(gain, key=gain.get) if gain else None
    best = best if best and gain[best] >= 0.5 else None
    _, first = readable_name(r)
    n_layout = sum(c["key"] in LAYOUT_CARDS and c["severity"] == "Critical" for c in top)
    rebuild = bool((r.get("layout_limits") or {}).get("active")) and n_layout > 0
    return {"now": now, "after": max(now, after), "n_fix": len(top), "first_name": first,
            "rebuild": rebuild, "n_layout": n_layout,
            "found": len(cards), "important": sum(c["severity"] == "Major" for c in cards),
            "critical": sum(c["severity"] == "Critical" for c in cards),
            "available": round(max(0.0, after - now), 1), "best_part": best,
            "best_gain": round(gain[best], 1) if best else 0.0}


def plain_name(i):
    """The page name of one scorer issue (its card's name in ISSUES; an AI finding keeps its own words)."""
    return i["name"] if i.get("ai") or i["id"] not in ISSUE_OF else ISSUES[ISSUE_OF[i["id"]]]["name"]


def card_part(c):
    return c["issues"][0]["part"]


def part_points(c):
    """What the card's problem costs its own part (the scorer's part points of its issues in that part)."""
    return round(sum(i.get("part_points", 0) for i in c["issues"] if i["part"] == card_part(c)), 1)


def count_note(c, r):
    """A short fact for the card's subtitle, counted in THIS resume (never a made-up number)."""
    key, vtext = c["key"], (r.get("_vdoc") or r["_doc"])["modern"]
    if key == "job_labels":
        found = {}
        for l in vtext.splitlines():
            if C.LABEL_LINE_RE.match(l.strip()):
                found[l.strip()] = found.get(l.strip(), 0) + 1
        if found:
            lab, n = max(found.items(), key=lambda kv: kv[1])
            return f'"{lab}" appears {n} time{"s" if n != 1 else ""}'
    if key == "repeated_numbers":
        pairs = re.findall(r"(\S+) \((\d+) times\)", r["content_checks"]["C9"]["detail"])
        if pairs:
            return ", ".join(f'"{n}" used {k} times' for n, k in pairs[:3])
    if key == "summary":
        c4 = r["content_checks"]["C4"]                  # the scorer's own count of the summary text only
        if c4.get("words"):
            return f"{c4['words']} words (keep it to 150 or fewer)"
    if key == "phone":
        before = phone_in(r)
        if before:
            return f"{before} → {phone_fixed(before)}"
    if key == "abbreviations_full":
        m = re.search(r"never written in full: (.+)$", r["content_checks"]["C12"]["detail"])
        if m:
            return "Not written in full: " + m.group(1)
    if key == "name_spacing":
        return "Some ATS read it as single letters"
    return ""


def phone_in(r):
    lines = C.contact_block(r.get("_vdoc") or r["_doc"])
    for l in lines:
        m = PHONE_IN_RE.search(l)
        if m and len(re.sub(r"\D", "", m.group(0))) >= 9:
            return m.group(0).strip()
    return None


def phone_fixed(phone):
    """'(+971) 585-516-848' -> '+971 58 551 6848'. Without a country code in the resume: '+[country code] ...'."""
    digits = re.sub(r"\D", "", phone)
    if not re.match(r"\(?\+", phone) and re.fullmatch(r"05\d{8}", digits):      # a UAE mobile number: 0505767221
        return f"+971 {digits[1:3]} {digits[3:6]} {digits[6:]}"
    m = re.match(r"\(?\+\s*\(?(\d{1,3})\)?", phone)
    rest = re.sub(r"\D", "", phone[m.end():] if m else phone)
    cc = m.group(1) if m else "[country code]"
    if not m:
        rest = rest.lstrip("0")
    groups = [rest[:2], rest[2:5], rest[5:]] if len(rest) == 9 else [rest[i:i + 3] for i in range(0, len(rest), 3)]
    return "+" + cc + " " + " ".join(g for g in groups if g)


def before_after(c, r):
    """(caption, lines now, lines after the fix or None). An 'after' is only shown when it can be made from the
    resume itself; placeholders in [brackets] mark what the person fills in."""
    show = c.get("show") or ISSUES[c["key"]]["show"]
    now = [l for l in evidence(c, r) if l]
    cap = REPORT_TEXT["now_ats" if show in ATS_SHOWS else "now_page"]
    key = c["key"]
    after = None
    if key == "headline":
        head = [x["text"] for x in C.analyse_cv(r.get("_vdoc") or r["_doc"])["header"][:3]]
        spaced_name = ((r.get("layout") or {}).get("findings") or {}).get("N1", {}).get("found")
        name = readable_name(r)[0] if spaced_name else None
        shown = headline_text(r)
        if head:
            now = [shown, "← no target role here"] if shown else [NOT_FOUND]
            after = [(name or candidate_name(r) or head[0], False), ("[Target title] | [Strength] | [Strength]", True)] + \
                [(x, False) for x in head[1:] if x != shown]
    elif key == "name_spacing":
        full = readable_name(r)[0]
        if now:
            after = [(full if full and not L.spaced_lines(full) else "[Your name in normal letters]", True)]
    elif key == "phone":
        p = phone_in(r)
        line = next((l for l in C.contact_block(r.get("_vdoc") or r["_doc"]) if p and p in l), None)
        if line:
            now, after = [line], [(line.replace(p, phone_fixed(p)), True)]
    elif key == "job_labels":
        lines = [l.strip() for l in (r.get("_vdoc") or r["_doc"])["modern"].splitlines() if l.strip()]
        at = next((k for k, l in enumerate(lines) if C.LABEL_LINE_RE.match(l)), None)
        if at is not None:
            now = lines[max(0, at - 1): at + 3]
            after = [(l, False) for l in now if not C.LABEL_LINE_RE.match(l)]
    elif key == "section_names":
        mapped = []
        for t in now:
            std = next((s for k, s in STANDARD_NAMES if k in t.lower()), None)
            if not std:
                mapped = []
                break
            mapped.append((std, True))
        after = mapped or None
    elif key == "dates":
        plain = [re.sub(r"\s+\([^()]*\)$", "", l) for l in now]
        fixed = [month_placeholders(l) for l in plain]
        if fixed != plain:
            after = [(l, True) for l in fixed]
    now = clean_quotes(now, r, key)
    if after:
        fixed = []
        for a in after:
            text, flag = a if isinstance(a, tuple) else (a, None)
            text = unspace_line(text)
            if not mixes_columns(text, r):
                fixed.append((text, flag) if isinstance(a, tuple) else text)
        after = fixed or None
    return cap, now, after


# ---------------------------------------------------------------------------
# HTML pieces (the page shows them; the downloadable report joins them)
# ---------------------------------------------------------------------------
def header_html(r):
    """The report's header: the title, the candidate, the resume file, the date and how it was checked, all plain
    text (no buttons, switches or file chips)."""
    name = candidate_name(r) or REPORT_TEXT["no_name"]
    job = r["mode"] == "job"
    how = REPORT_TEXT["with_job_plain"] if job else REPORT_TEXT["without_job_plain"]
    meta = "".join(f'<div class="rm"><dt>{k}</dt><dd>{v}</dd></div>' for k, v in (
        (REPORT_TEXT["candidate"], esc(name)), (REPORT_TEXT["file"], esc(r["cv"])),
        (REPORT_TEXT["date"], L.TODAY.strftime("%d %B %Y").lstrip("0")))
        + (((REPORT_TEXT["job_title"], esc(r["target"])),) if job and r.get("target") else ())
        + ((REPORT_TEXT["checked"], how),))
    return (f'<div class="rh"><div class="rh-top"><div class="logo">1K</div><h1>{REPORT_TEXT["report_title"]}</h1></div>'
            f'<dl class="rh-meta">{meta}</dl></div>')


def candidate_name(r):
    """The candidate's name from the resume without titles and credentials ('MOHAMED SHOKRY, MBA' -> 'Mohamed
    Shokry', 'SANA MALIK, PMP®' -> 'Sana Malik', 'Dr. Jane Doe' -> 'Jane Doe'), or None."""
    try:
        full = readable_name(r)[0]
    except Exception:
        full = None
    if not full:
        return None
    name = L.bare_name(full)
    if not name:
        return None
    return name.title() if name.isupper() or name.islower() else name


def report_file_name(r, ext="pdf", original=None):
    """'1000Jobs ATS Lab - Mohamed Shokry - 2026-10-25.pdf' (the resume's file name when no name is found). With the
    `original` resume (the client comparison report): '1000Jobs ATS Lab - Mohamed Shokry - Comparison - 2026-10-25.pdf'."""
    base = candidate_name(r) or (candidate_name(original) if original is not None else None) \
        or os.path.splitext(r.get("cv") or "resume")[0]
    base = re.sub(r'[<>:"/\|?*\x00-\x1f]', " ", base)
    base = re.sub(r"\s+", " ", base).strip(" .") or "resume"
    kind = f" - {CLIENT_TEXT['file_kind']}" if original is not None else ""
    return f"1000Jobs ATS Lab - {base[:80]}{kind} - {L.TODAY.isoformat()}.{ext}"


def score_html(r, cards, plain=False):
    s = report_summary(r, cards)
    who = REPORT_TEXT["who"].format(name=esc(s["first_name"])) if s["first_name"] else REPORT_TEXT["who_unknown"]
    big = headline_sentence(s, who)
    rd = r["parts"]["readability"]
    lead = REPORT_TEXT["read_well" if rd >= 85 else "read_ok" if rd >= 60 else "read_bad"]
    if s["best_part"]:
        names = [lower_first(c["name"]) for c in cards if card_part(c) == s["best_part"]][:2]
        if names:
            lead += " " + REPORT_TEXT["most_lost"].format(part=PART_NAMES[s["best_part"]],
                                                          issues=esc(" and ".join(names)))
    bg, fg = LABEL_COLORS.get(r["label"], ("#f1f5f9", "#334155"))
    checked = REPORT_TEXT["checked_job"].format(target=esc(r["target"])) if r["mode"] == "job" else \
        REPORT_TEXT["checked_std"]
    counts = (f'<span class="count"><b>{s["found"]}</b>{REPORT_TEXT["found"]}</span>'
              + (f'<span class="count c-crit"><b>{s["critical"]}</b>{REPORT_TEXT["critical"]}</span>'
                 if s["critical"] else "")
              + f'<span class="count c-imp"><b>{s["important"]}</b>{REPORT_TEXT["important"]}</span>'
              + (f'<span class="count c-gain"><b>+{fmt(s["available"])}</b>'
                 f'{REPORT_TEXT["available"].format(n=s["n_fix"], es="es" if s["n_fix"] != 1 else "")}</span>'
                 if s["n_fix"] else ""))
    bar = (f'<div class="barlbl"><span>{REPORT_TEXT["now"].format(now=fmt(s["now"]))}</span>'
           f'<span class="aft">{REPORT_TEXT["after"].format(after=fmt(s["after"]))}</span></div>'
           f'<div class="bar"><i style="width:{s["after"]:.0f}%;background:#fde68a"></i>'
           f'<i style="width:{s["now"]:.0f}%;background:{color_for(s["now"])}"></i></div>') if s["n_fix"] else ""
    held = f'<div class="note">{REPORT_TEXT["held"]}</div>' if any("no numbers" in g for g in r["gates"]) else ""
    return (f'<div class="card"><div class="score"><div class="ring">{gauge(r["score"], 170)}'
            f'<div class="of">{REPORT_TEXT["out_of"]}</div></div><div class="sbody">'
            f'<span class="lbl" style="background:{bg};color:{fg}">{esc(r["label"])}</span>'
            f'<span class="muted">{checked} · <span class="nw">{L.TODAY.strftime("%d %b %Y").lstrip("0")}</span></span>'
            f'<div class="big">{big}</div><p class="lead">{lead}</p>{bar}<div class="counts">{counts}</div>'
            f'{held}</div></div>' + (f'<div class="plain">{REPORT_TEXT["plain_job" if r["mode"] == "job" else "plain"].format(score=fmt(r["score"]))}</div>'
                                     if plain else "") + '</div>')


def education_good(r):
    """The good line for Education: 'with school and year' only when EVERY degree has its year."""
    t9 = (r.get("structure_checks") or {}).get("T9") or {}
    if t9.get("every_year"):
        return "Education lists degrees with school and year"
    if t9.get("year_hidden"):
        return "Education lists degrees with school (year hidden: fine with 10+ years of experience)"
    return None


def why_part(r, part, cards=None):
    """For one part, from the scorer's own numbers (r["part_explain"]): what is good, each issue that lowered the
    part with the points it cost (same plain name as its card; ids of one card added together), and what holds
    the part back. -> {"good", "items": [(name, points)], "gains": {name: Resume Score points}, "other",
    "blocked", "loss"}."""
    e = r["part_explain"][part]
    mine = [i for i in r["issues"] if i["part"] == part]
    ids = {i["id"] for i in mine}
    good = [education_good(r) if t == "EDUCATION" else t for need, t in GOOD.get(part, []) if not need & ids]
    good = [t for t in good if t][:MAX_WHY_GOOD]
    cards = issue_cards(r) if cards is None else cards
    # each row is one issue card (same name, same +pts); an issue merged into a card of ANOTHER part keeps its
    # own plain name and points here
    names, gains = {}, {}
    for c in cards:
        for i in c["issues"]:
            if i["part"] == card_part(c):
                names[i["id"]], gains[c["name"]] = c["name"], c["points"]
            else:
                n = plain_name(i)
                names[i["id"]], gains[n] = n, max(gains.get(n, 0.0), i["points"])
    items = {}
    for x in e["items"]:
        n = names.get(x["id"], x["name"])
        items[n] = round(items.get(n, 0) + x["points"], 1)
    ranked = sorted(items.items(), key=lambda kv: -kv[1])
    shown = ranked[:MAX_WHY_ISSUES]
    other = round(e["other"] + sum(p for _, p in ranked[MAX_WHY_ISSUES:]), 1)
    blocked = next((i["blocked_by"] for i in mine if i.get("blocked_by")), None) \
        if mine and all(i["points"] < 0.5 for i in mine) else None
    return {"good": good, "items": shown, "gains": gains, "other": other, "loss": e["loss"],
            "blocked": WHY_TEXT["blocked"].format(first=BLOCKED_FIRST[blocked]) if blocked else None}


def part_card_html(r, part, best=False, cards=None):
    w = why_part(r, part, cards)
    v = r["parts"][part]
    rows = "".join(f'<div class="ok">{esc(t)}</div>' for t in w["good"])
    lost = "".join(f'<div class="row"><span class="nm">{esc(n)}</span><span class="pt"><b>−{fmt(p)}</b>'
                   + (f'<span>+{fmt(w["gains"][n])}</span>' if w["gains"].get(n, 0) >= 0.1 else "")
                   + "</span></div>" for n, p in w["items"])
    if w["other"] >= 0.5:
        lost += (f'<div class="row small"><span class="nm">{REPORT_TEXT["smaller"]}</span>'
                 f'<span class="pt"><b>−{fmt(w["other"])}</b></span></div>')
    if not lost:
        lost = f'<div class="row small"><span class="nm">{REPORT_TEXT["perfect"]}</span></div>'
    blk = f'<div class="blk">{esc(w["blocked"])}</div>' if w["blocked"] else ""
    tag = f'<div class="best-tag">{REPORT_TEXT["biggest"]}</div>' if best else ""
    return (f'<div class="card part{" best" if best else ""}">{tag}<div class="ph"><span class="n">{PART_NAMES[part]}'
            f'</span><span class="v" style="color:{color_for(v)}">{fmt(v)}</span></div>'
            f'<div class="bar"><i style="width:{v:.0f}%;background:{color_for(v)}"></i></div>'
            f'<div class="scale">{REPORT_TEXT["scale"].format(part=PART_NAMES[part])}</div>{rows}'
            f'<div class="sep"></div>{lost}{blk}</div>')


def parts_html(r, cards):
    best = report_summary(r, cards)["best_part"]
    return '<div class="parts">' + "".join(part_card_html(r, p, p == best, cards) for p in PART_NAMES
                                           if p in r["parts"]) \
        + "</div>"


def issue_html(n, c, r, opened=False):
    pts = (f'<span class="gain">+{fmt(c["points"])} pt{"" if fmt(c["points"]) == "1" else "s"}</span>' if c["points"] >= 0.1 else
           f'<span class="gain wait">{esc(BLOCKED_FIRST[c["blocked_by"]])}, then +{fmt(c["points_after"])}</span>'
           if c.get("blocked_by") else "")
    meta = [c["tag"], PART_NAMES.get(card_part(c), "")]
    if part_points(c) >= 0.1:
        meta.append(REPORT_TEXT["part_cost"].format(p=fmt(part_points(c)), part=PART_NAMES.get(card_part(c), "")))
    note = count_note(c, r)
    if note:
        meta.append(note)
    if c.get("ai"):
        meta.append(REPORT_TEXT["ai_ok" if c["issues"][0]["ai"].get("confirmed") else "ai"])
    cap, now, after = before_after(c, r)
    now_html = "".join(f'<span class="gone">{esc(l)}</span>' if l.startswith("←") else esc(l) + "<br>"
                       for l in now) or esc(REPORT_TEXT["nothing_shown"])
    ba = f'<div><div class="cap">{cap}</div><div class="code now">{now_html}</div></div>'
    if after:
        ba += (f'<div><div class="cap">{REPORT_TEXT["after_fix"]}</div><div class="code aft">'
               + "".join(f'<span class="new">{esc(l)}</span>' if new else esc(l) + "<br>" for l, new in after)
               + "</div></div>")
    also = f'<div class="also">{esc(REPORT_TEXT["also"].format(names="; ".join(c["also"])))}</div>' \
        if c.get("also") else ""
    return (f'<details class="iss"{" open" if opened else ""}><summary><span class="num {c["tag"]}">{n}</span>'
            f'<span class="it"><div class="t">{esc(c["name"])}</div><div class="m">{esc(" · ".join(meta))}</div>'
            f'</span>{pts}</summary><div class="ib"><div class="ba">{ba}</div><div class="wf">'
            f'<div><b>{REPORT_TEXT["why_hurts"]}</b>{esc(c["why"])}</div>'
            f'<div><b>{REPORT_TEXT["how_fix"]}</b>{esc(c["fix"])}</div></div>{also}</div></details>')


def issues_html(r, cards, all_open=False):
    if not cards:
        return f'<h2>{REPORT_TEXT["top"]}</h2><div class="sub">{REPORT_TEXT["no_issues"]}</div>'
    first = "".join(issue_html(n, c, r, opened=all_open or n == 1) for n, c in enumerate(cards[:TOP_CARDS], 1))
    rest = "".join(issue_html(n, c, r, opened=all_open) for n, c in enumerate(cards[TOP_CARDS:], TOP_CARDS + 1))
    k = len(cards) - TOP_CARDS
    if rest:
        rest = (f'<details class="more"{" open" if all_open else ""}><summary>'
                f'{REPORT_TEXT["more"].format(n=k, s="s" if k != 1 else "")}</summary>{rest}</details>')
    head, first = first.split("</details>", 1)
    return (f'<div class="keep"><h2>{REPORT_TEXT["top"]}</h2><div class="sub">{REPORT_TEXT["top_sub"]}</div>'
            f'{head}</details></div>{first}{rest}')


def improve_items(cards):
    """'What we'll fix': one line per issue found in this resume (biggest gain first), the same fix never twice,
    at most MAX_IMPROVE. -> [{"fix": what 1000Jobs does, "issue": the issue it fixes, "points": its +pts}]."""
    out = []
    for c in cards:
        if c["we_fix"] not in [x["fix"] for x in out]:
            out.append({"fix": c["we_fix"], "issue": c["name"], "points": c["points"]})
    return out[:MAX_IMPROVE]


def improve_html(cards):
    items = improve_items(cards)
    fix = "".join(f'<div class="fx"><span class="d">{n}</span><span class="x"><b>{esc(x["fix"])}</b>'
                  f'<span>{esc(REPORT_TEXT["fixes"].format(issue=lower_first(x["issue"])))}</span></span>'
                  + (f'<span class="p">+{fmt(x["points"])}</span>' if x["points"] >= 0.1 else "") + "</div>"
                  for n, x in enumerate(items, 1)) or f'<div class="fx"><span class="x">{esc(IMPROVE_TEXT["nothing"])}</span></div>'
    why = "".join(f'<div class="wl"><i>&#10003;</i><span>{esc(t)}</span></div>' for t in IMPROVE_TEXT["why"])
    return (f'<div class="imp"><div class="card"><h3>{IMPROVE_TEXT["title"]}</h3><div class="sub">'
            f'{IMPROVE_TEXT["sub"]}</div>{fix}</div><div class="card why"><h3>{IMPROVE_TEXT["why_title"]}</h3>{why}'
            f'</div></div>')


def skills_html(r):
    if r["mode"] != "job":
        return ""
    missing = [k for k in r["v3"]["keywords"] if k["match"] == "missing" and k["type"] != "soft"]
    body = (f'<div class="sub">Missing keywords - add only the ones you really have. Red = required by the job.</div>'
            + chips([k["term"] for k in missing if k["type"] == "required"], "req")
            + chips([k["term"] for k in missing if k["type"] != "required"])) if missing else \
        '<div class="sub">Every keyword from the job was found in your resume.</div>'
    return (f'<h2>Job Match</h2><div class="card">Your resume matches <b>{fmt(r["parts"]["job_match"])}%</b> of what '
            f'this job asks for.{body}</div>')


def versions_html(r):
    """One note at the top when the file has a designed version and a text version of the resume."""
    two = r.get("two_versions")
    return f'<div class="note vers">{esc(two["note"])}</div>' if two else ""


def report_body(r, cards, all_open=False):
    return ('<div class="rp">' + header_html(r) + versions_html(r) + score_html(r, cards, plain=True) + parts_html(r, cards)
            + issues_html(r, cards, all_open) + skills_html(r) + improve_html(cards) + "</div>")


def report_document(r, cards=None):
    """The downloadable report: one HTML file, every issue open, made to print on A4 without cut or overlapping text."""
    cards = issue_cards(r) if cards is None else cards
    title = esc(f"Resume report - {r['cv']}")
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" '
            f'content="width=device-width, initial-scale=1"><title>{title}</title><link rel="stylesheet" '
            f'href="{FONT_URL}"><style>{REPORT_CSS}{PRINT_CSS}'
            f'</style></head><body>{report_body(r, cards, all_open=True)}</body></html>')


# ---------------------------------------------------------------------------
# The client comparison report: the client's original resume (old) next to our 1000Jobs resume (new). Exactly 3
# sections (Compared, Improved, Issues in the original resume), then "Why 1000Jobs". Nothing here describes a problem
# of the 1000Jobs resume: no issues, cards, "still not fixed", "new in this version", "can reach" or points lost.
# ---------------------------------------------------------------------------
def client_header_html(old, new):
    name = candidate_name(new) or candidate_name(old) or REPORT_TEXT["no_name"]
    job = new["mode"] == "job"
    how = REPORT_TEXT["with_job_plain"] if job else REPORT_TEXT["without_job_plain"]
    meta = "".join(f'<div class="rm"><dt>{k}</dt><dd>{v}</dd></div>' for k, v in (
        (REPORT_TEXT["candidate"], esc(name)), (CLIENT_TEXT["original_file"], esc(old["cv"])),
        (CLIENT_TEXT["ours_file"], esc(new["cv"])), (REPORT_TEXT["date"], L.TODAY.strftime("%d %B %Y").lstrip("0")))
        + (((REPORT_TEXT["job_title"], esc(new["target"])),) if job and new.get("target") else ())
        + ((REPORT_TEXT["checked"], how),))
    return (f'<div class="rh"><div class="rh-top"><div class="logo">1K</div><h1>{CLIENT_TEXT["report_title"]}</h1>'
            f'</div><dl class="rh-meta">{meta}</dl></div>')


def change_text(before, after):
    d = round(after) - round(before)
    return CLIENT_TEXT["change"].format(sign="+" if d >= 0 else "−", change=abs(d))


def compared_html(cmp, old=None, new=None):
    """The two scores side by side - the original resume on the left, our 1000Jobs resume on the right - each with the
    file it belongs to under it, so a file in the wrong place is impossible to miss."""
    d = round(cmp["new"]) - round(cmp["old"])
    side = lambda cls, key, score, name, extra="": (
        f'<div class="{cls}">{gauge(score, 96)}<div><div class="who">{CLIENT_TEXT[key].format(score=fmt(score))}'
        f'{extra}</div><div class="file">{esc(name)}</div></div></div>')
    chg = f' <span class="chg{" down" if d < 0 else ""}">({change_text(cmp["old"], cmp["new"])})</span>'
    rows = "".join(f'<tr><td>{PART_NAMES[p]}</td><td>{fmt(a)}</td><td>{fmt(b)}</td><td>{change_text(a, b)}</td></tr>'
                   for p, a, b in cmp["parts"])
    return (f'<h2>{CLIENT_TEXT["compared"]}</h2><div class="sub">{CLIENT_TEXT["compared_sub"]}</div><div class="card">'
            f'<div class="cmp">{side("old", "original", cmp["old"], (old or {}).get("cv") or "")}'
            f'{side("ours", "ours", cmp["new"], (new or {}).get("cv") or "", chg)}</div>'
            f'<table class="pt"><tr><th>{CLIENT_TEXT["part"]}</th><th>{CLIENT_TEXT["col_original"]}</th>'
            f'<th>{CLIENT_TEXT["col_ours"]}</th><th>{CLIENT_TEXT["col_change"]}</th></tr>{rows}</table></div>')


def improved_html(cmp, old, other=None):
    items = "".join(f'<div class="imv"><i>&#10003;</i><div><div class="t">{esc(c["name"])}</div>'
                    f'<div class="cap">{CLIENT_TEXT["before"]}</div>'
                    f'<div class="code now">{"<br>".join(esc(l) for l in short_quote(c, old, other))}</div>'
                    f'<div class="chd"><b>{CLIENT_TEXT["changed"]}:</b> {esc(c["we_fix"])}</div></div></div>'
                    for c in cmp["improved"]) or f'<div class="sub">{CLIENT_TEXT["none_improved"]}</div>'
    return f'<h2>{CLIENT_TEXT["improved"]}</h2><div class="sub">{CLIENT_TEXT["improved_sub"]}</div>{items}'


def original_issue_html(n, c, old, other=None):
    meta = " · ".join(x for x in (c["tag"], PART_NAMES.get(card_part(c), ""),
                                  REPORT_TEXT["ai"] if c.get("ai") else "") if x)
    return (f'<div class="ci"><div class="hd"><span class="num {c["tag"]}">{n}</span><span class="it"><div class="t">'
            f'{esc(c["name"])}</div><div class="m">{esc(meta)}</div></span></div><div class="ib"><div class="ba"><div>'
            f'<div class="cap">{CLIENT_TEXT["quote"]}</div><div class="code now">'
            f'{"<br>".join(esc(l) for l in short_quote(c, old, other))}</div></div></div><div class="wf">'
            f'<div><b>{REPORT_TEXT["why_hurts"]}</b>{esc(c["why"])}</div>'
            f'<div><b>{REPORT_TEXT["how_fix"]}</b>{esc(c["fix"])}</div></div></div></div>')


def original_issues_html(cmp, old, other=None):
    body = "".join(original_issue_html(n, c, old, other) for n, c in enumerate(cmp["issues"], 1)) or \
        f'<div class="sub">{CLIENT_TEXT["no_issues"]}</div>'
    return f'<h2>{CLIENT_TEXT["issues"]}</h2><div class="sub">{CLIENT_TEXT["issues_sub"]}</div>{body}'


def why_1000jobs_html():
    why = "".join(f'<div class="wl"><i>&#10003;</i><span>{esc(t)}</span></div>' for t in IMPROVE_TEXT["why"])
    return f'<div class="imp"><div class="card why"><h3>{IMPROVE_TEXT["why_title"]}</h3>{why}</div></div>'


def comparison_body(old, new):
    """The 3 sections and "Why 1000Jobs" (the page shows this; the PDF adds the header)."""
    cmp = client_comparison(old, new)
    return compared_html(cmp, old, new) + improved_html(cmp, old, new) + original_issues_html(cmp, old, new) \
        + why_1000jobs_html()


def comparison_document(old, new):
    """The client comparison report as one HTML file, made to print on A4."""
    title = esc(f"Resume comparison - {old['cv']} - {new['cv']}")
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" '
            f'content="width=device-width, initial-scale=1"><title>{title}</title><link rel="stylesheet" '
            f'href="{FONT_URL}"><style>{REPORT_CSS}{CLIENT_CSS}{PRINT_CSS}</style></head><body><div class="rp">'
            f'{client_header_html(old, new)}{comparison_body(old, new)}</div></body></html>')


def client_document(main, previous, swap=None):
    """The client comparison report for the two files as they were uploaded: `main` is the file in the 1000Jobs slot
    and `previous` the file in the user's own resume slot (see client_pair for `swap`). The roles are decided here,
    once, and everything below works with them, so a Swap the team pressed is never undone further down."""
    old, new = client_pair(main, previous, swap)[:2]
    return comparison_document(old, new)


# ---------------------------------------------------------------------------
# The PDF: the report page printed by the computer's own browser (Edge or Chrome, no window), so the PDF has exactly
# the fonts and colors of the dashboard. If that fails, the HTML report is offered instead.
# ---------------------------------------------------------------------------
BROWSER_PATHS = (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                 r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
                 r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                 r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                 "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser",
                 "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
PDF_TIMEOUT = 120
PDF_MIN_BYTES = 2000


class PdfError(Exception):
    """The PDF could not be created (the message says why, in plain words)."""


def find_browser():
    """Edge or Chrome on this computer (ATSLAB_BROWSER = a path to use instead), or None."""
    env = os.environ.get("ATSLAB_BROWSER")
    if env and os.path.exists(env):
        return env
    found = next((p for p in BROWSER_PATHS if os.path.exists(p)), None)
    if found:
        return found
    import shutil
    return next((w for w in map(shutil.which, ("msedge", "google-chrome", "chrome", "chromium")) if w), None)


def make_pdf(html_doc, timeout=None):
    """The report (HTML text) as PDF bytes. Raises PdfError when there is no browser or it cannot print."""
    import shutil
    import subprocess
    exe = find_browser()
    if not exe:
        raise PdfError("no Edge or Chrome browser found")
    os.makedirs(TMP_DIR, exist_ok=True)
    work = tempfile.mkdtemp(dir=TMP_DIR)
    try:
        src, out = os.path.join(work, "report.html"), os.path.join(work, "report.pdf")
        with open(src, "w", encoding="utf-8") as f:
            f.write(html_doc)
        last = "the browser did not make a file"
        for head in ("--headless=new", "--headless"):
            cmd = [exe, head, "--disable-gpu", "--no-pdf-header-footer", "--virtual-time-budget=8000",
                   f"--user-data-dir={os.path.join(work, 'profile')}", f"--print-to-pdf={out}",
                   "file:///" + src.replace("\\", "/").lstrip("/")]
            if os.name != "nt":                      # a server or a Docker container: Chromium needs no sandbox there
                cmd.insert(2, "--no-sandbox")
            try:
                subprocess.run(cmd, check=True, timeout=timeout or PDF_TIMEOUT, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
            except subprocess.TimeoutExpired:
                last = "the browser took too long"
                continue
            except (OSError, subprocess.CalledProcessError) as e:
                last = f"the browser stopped ({type(e).__name__})"
                continue
            if os.path.exists(out):
                with open(out, "rb") as f:
                    data = f.read()
                if data[:5] == b"%PDF-" and len(data) >= PDF_MIN_BYTES:
                    return data
                last = "the file the browser made is not a PDF"
        raise PdfError(last)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def pdf_for(r, cards, cache=None):
    """-> (bytes or None, reason). Made once per report (kept in `cache`, a dict, e.g. the session state)."""
    return pdf_of(report_document(r, cards), cache)


def pdf_of(doc, cache=None):
    """A report document (HTML text) as a PDF: -> (bytes or None, reason), made once per document."""
    key = hashlib.sha256(doc.encode("utf-8")).hexdigest()[:20]
    cache = {} if cache is None else cache
    if key not in cache:
        try:
            cache[key] = (make_pdf(doc), "")
        except PdfError as e:
            cache[key] = (None, str(e))
        except Exception as e:                       # never let the download fail with an error page
            cache[key] = (None, f"{type(e).__name__}")
    return cache[key]


# ---------------------------------------------------------------------------
# Page sections (Streamlit)
# ---------------------------------------------------------------------------
def show_compare(old, r):
    cmp = compare_versions(old, r)
    st.subheader("Compared with the previous resume")
    with st.container(border=True):
        delta = cmp["score_after"] - cmp["score_before"]
        st.markdown(f"Resume Score **{cmp['score_before']:.0f} → {cmp['score_after']:.0f}** "
                    f"({'+' if delta >= 0 else ''}{delta:.0f})")
        a, b = st.columns(2)
        with a:
            st.markdown("**Fixed since last version**")
            for n in cmp["fixed"]:
                st.markdown(f"✅ {n}")
            if not cmp["fixed"]:
                st.caption("Nothing fixed yet.")
        with b:
            st.markdown("**Still not fixed**")
            for n in cmp["still"]:
                st.markdown(f"⏳ {n}")
            if not cmp["still"]:
                st.caption("Nothing left from the previous version.")
        if cmp["new"]:
            st.markdown("**New in this version:** " + ", ".join(cmp["new"]))


def gain_text(c, long=False):
    """'+4 points if fixed', or for a blocked fix 'Fix the layout issues first, then this adds about +6'."""
    if c["points"] >= 1:
        n = round(c["points"])
        return f"about +{n} on your Resume Score" if long else f"+{n} point{'s' if n != 1 else ''} if fixed"
    if c.get("blocked_by"):
        return f"{BLOCKED_FIRST[c['blocked_by']]}, then this adds about +{c['points_after']:.0f}"
    return ""


def html_block(body):
    st.markdown('<div class="rp">' + body + "</div>", unsafe_allow_html=True)


def show_details(r):
    v3 = r["v3"]
    with st.expander("Details"):
        st.markdown("**Scores in each ATS** (Greenhouse is the most flexible, Oracle the strictest)")
        rows = []
        for p in ("greenhouse", "workday", "oracle"):
            a = v3["ats"][p]
            row = {"ATS": p.capitalize(), "Can read it": a["readable"]}
            if r["mode"] == "job":
                row.update({"Can find it": a["findable"], "Fits the job": a["matched"], "Total": a["total"]})
            rows.append(row)
        st.dataframe(rows, hide_index=True, width="stretch")

        st.markdown("**What the ATS sees**")
        f = v3["ats_view"]["fields"]
        show = lambda v: v or "not found"
        a, b = st.columns(2)
        a.markdown(f"Name: {show(f['name'])}  \nEmail: {show(f['email'])}  \nPhone: {show(f['phone'])}")
        b.markdown(f"Location: {show(f['location'])}  \nLinkedIn: {show(f['linkedin'])}  \n"
                   f"Headline: {show(f['headline'])}")
        if f["jobs"]:
            st.dataframe([{"Job title": j["title"], "Company": j["company"] or "", "Dates": j["dates"] or "",
                           "Looks wrong": "; ".join(x for x in (j["title_problem"], j["date_problem"]) if x)}
                          for j in f["jobs"]], hide_index=True, width="stretch")
        st.markdown(f"Education: {'; '.join(f['education']) if f['education'] else 'not found'}  \n"
                    f"Skills ({len(f['skills'])}): {', '.join(f['skills']) if f['skills'] else 'not found'}")
        st.markdown("Plain text the ATS extracts:")
        st.text(v3["ats_view"]["text_strict"])

        ai = r.get("ai_review") or {}
        unusual = ai.get("unusual") or []
        st.markdown(f"**Possible new problems** ({len(v3['possible_new_bugs']) + len(unusual)}) - not scored, "
                    f"for the team to check")
        if not v3["possible_new_bugs"] and not unusual:
            st.caption("Nothing unusual found.")
        for x in v3["possible_new_bugs"]:
            st.markdown(f"- {x['kind'].capitalize()}: {html.escape(x['detail'])}")
        for x in unusual:
            st.markdown(f"- AI reviewer: {html.escape(x['issue'])}: \"{html.escape(x['quote'])}\"")
        verify = r.get("to_verify") or []
        st.markdown(f"**To verify by the team** ({len(verify)}) - a rule the rendered page or the golden set does "
                    f"not support: not scored, and not shown to the user")
        if not verify:
            st.caption("Nothing to verify.")
        for v in verify:
            st.markdown(f"- {html.escape(v.get('name') or v.get('id'))}: {html.escape(v.get('why') or '')}"
                        + (f"  \n  the rule found: {html.escape(v['detail'])}" if v.get("detail") else ""))
        if r.get("ai_review") is None:
            st.caption("The AI reviewer did not run (no API key).")
        else:
            st.caption(f"AI reviewer: {len(ai['findings'])} finding(s) checked against the resume text"
                       + (f"; {ai['rejected']} left out because their quote is not in the resume" if ai["rejected"] else ""))


def render(r, with_job=None, previous=None, client=False, swapped=None):
    if client and previous is not None:              # the client comparison report: its 3 sections only
        return render_client(previous, r, swapped)
    if client:
        st.info(CLIENT_TEXT["need_original"])
    cards = issue_cards(r)
    for note in r.get("notes") or []:               # a part that could not run on this computer, said plainly
        st.info(note)
    html_block(score_html(r, cards) + parts_html(r, cards))
    slot = st.empty()                               # the download button: filled last, after the PDF is made
    slot.caption(REPORT_TEXT["pdf_preparing"])
    if previous is not None:
        show_compare(previous, r)
    html_block(issues_html(r, cards) + skills_html(r) + improve_html(cards))
    st.write("")
    show_details(r)
    show_download(slot, r, cards)


def render_client(old, new, swapped=None):
    """The client comparison report on the page: the same 3 sections and "Why 1000Jobs" as its PDF. The roles are
    decided here, once (see client_pair), and said plainly, so a file in the wrong slot is easy to spot."""
    old, new, other_way = client_pair(new, old, swapped)
    if other_way:                                   # said plainly: the two files were read the other way round
        st.caption(CLIENT_TEXT["swapped"].format(ours=new["cv"], original=old["cv"]))
    slot = st.empty()
    slot.caption(REPORT_TEXT["pdf_preparing"])
    st.markdown(f"<style>{CLIENT_CSS}</style>", unsafe_allow_html=True)
    html_block(comparison_body(old, new))
    show_download(slot, new, None, original=old)


def show_download(slot, r, cards, original=None):
    """'Download PDF' (a real PDF made from the report; with the `original` resume: the client comparison report).
    When the PDF cannot be made: a clear message and the HTML report instead, so the download never just fails."""
    cache = st.session_state.setdefault("pdf_cache", {})
    doc = report_document(r, cards) if original is None else comparison_document(original, r)
    data, why = pdf_of(doc, cache)
    with slot.container():
        if data:
            st.download_button(REPORT_TEXT["download"], data, file_name=report_file_name(r, "pdf", original),
                               mime="application/pdf", type="primary", key="download_pdf")
        else:
            st.warning(REPORT_TEXT["pdf_failed"].format(why=why))
            st.download_button(REPORT_TEXT["download_html"], doc.encode("utf-8"),
                               file_name=report_file_name(r, "html", original), mime="text/html", key="download_html")


FILE_ICON = ('<svg width="14" height="16" viewBox="0 0 14 16" fill="none"><path d="M2 1h7l4 4v10H2z" '
             'stroke="#64748b" stroke-width="1.4" stroke-linejoin="round"/><path d="M9 1v4h4" stroke="#64748b" '
             'stroke-width="1.4" stroke-linejoin="round"/></svg>')


def brand_html():
    return (f'<div class="atsl-brand"><div class="logo">1K</div><div><div class="app">{REPORT_TEXT["app"]}</div>'
            f'<div class="tag">{REPORT_TEXT["tagline"]}</div></div></div>')


def file_chip_html(r):
    size = f'<span class="sz">{r["_size"] / 1024:.1f} KB</span>' if r.get("_size") else ""
    return f'<div class="atsl-chip" title="{esc(r["cv"])}">{FILE_ICON}<span class="nm">{esc(r["cv"])}</span>{size}</div>'


def start_new():
    """'Check new resume': forget the result and show an empty upload card."""
    st.session_state.pop("result", None)
    st.session_state["upload_round"] = st.session_state.get("upload_round", 0) + 1


def top_bar(saved):
    """The slim top bar: logo and name, the checked file, the With / Without switch, 'Check new resume'."""
    with st.container(key="atsl-topbar"):
        brand, chip, switch, new = st.columns([2.6, 2.5, 2.9, 1.9], vertical_alignment="center")
        brand.markdown(brand_html(), unsafe_allow_html=True)
        if saved:
            chip.markdown(file_chip_html(saved["res"]), unsafe_allow_html=True)
        with switch:
            mode = st.radio("Do you have a job description?", (WITH_JOB, WITHOUT_JOB), horizontal=True,
                            label_visibility="collapsed", key="mode",
                            format_func=lambda m: REPORT_TEXT["without"] if m == WITHOUT_JOB else m)
        new.button(REPORT_TEXT["new"], type="primary", on_click=start_new)
    return mode


def upload_card(mode):
    """Before a resume is checked: the upload area (and the job description box with a job)."""
    round_ = st.session_state.get("upload_round", 0)
    with st.container(key="atsl-upload"):
        st.markdown(f'### {REPORT_TEXT["upload_title"]}')
        st.caption(REPORT_TEXT["upload_sub"])
        upload = st.file_uploader("Upload one resume (PDF)", type=UPLOAD_TYPES, key=f"upload_{round_}")
        title = ""
        if mode == WITH_JOB:
            title = st.text_input(REPORT_TEXT["job_title_label"], placeholder=REPORT_TEXT["job_title_hint"],
                                  help=REPORT_TEXT["job_title_help"], key=f"job_title_{round_}")
            text = st.text_area("Job description", height=180, placeholder="Paste the full job description here",
                                key=f"job_{round_}")
        else:
            st.caption(REPORT_TEXT["std_note"])
            text = ""
        with st.expander("Compare with a previous resume (optional)"):
            prev_upload = st.file_uploader("Upload the previous version (PDF)", type=UPLOAD_TYPES,
                                           key=f"previous_{round_}")
            client = st.checkbox(CLIENT_TEXT["checkbox"], key=f"client_{round_}")
        clicked = st.button("Check resume", type="primary", width="stretch")
    if clicked:
        return {"pdf": upload.getvalue() if upload else b"", "name": upload.name if upload else "",
                "with_job": mode == WITH_JOB, "text": text, "job_title": title,
                "prev_pdf": prev_upload.getvalue() if prev_upload is not None else None,
                "prev_name": prev_upload.name if prev_upload is not None else None, "client": client}
    return None


def again_card(mode, saved):
    """The switch was changed after a check: check the same resume again in the other mode."""
    with st.container(key="atsl-upload"):
        title = ""
        if mode == WITH_JOB:
            st.caption(REPORT_TEXT["again_job"])
            title = st.text_input(REPORT_TEXT["job_title_label"], placeholder=REPORT_TEXT["job_title_hint"],
                                  help=REPORT_TEXT["job_title_help"],
                                  key=f"again_title_{st.session_state.get('upload_round', 0)}")
            text = st.text_area("Job description", height=160, placeholder="Paste the full job description here",
                                key=f"again_job_{st.session_state.get('upload_round', 0)}")
        else:
            st.caption(REPORT_TEXT["again_std"])
            text = ""
        if st.button(REPORT_TEXT["again"], type="primary"):
            return dict(saved["inputs"], with_job=mode == WITH_JOB, text=text, job_title=title)
    return None


def current_result():
    """The saved result, recalculated (or dropped) when an older version of the scoring made it."""
    saved = st.session_state.get("result")
    if saved is None:
        return None
    if not isinstance(saved, dict) or not is_current(saved.get("res")) \
            or (saved.get("prev") is not None and not is_current(saved["prev"])):
        # made by an older version of the scoring (e.g. before the layout checks): recalculate, never crash
        if isinstance(saved, dict) and saved.get("inputs"):
            st.info("This result was made by an older version of the scoring, so it was calculated again.")
            check_and_store(saved["inputs"])
        else:
            st.session_state.pop("result", None)
            st.info("The scoring was updated since this resume was checked. Press \"Check resume\" to see the new "
                    "result.")
    return st.session_state.get("result")


def main(after_check=None, page_config=True, below_top=None, gate=None):
    """The checking page. after_check(saved): called after each new check (the Admin page saves it to the history);
    page_config=False when app.py has already set up the page; below_top(): draws a bar under the top bar;
    gate(): a context manager each check runs inside (the app's queue: only a few checks at once)."""
    if page_config:
        st.set_page_config(page_title="1000Jobs ATS Lab", layout="centered")
    if not st.session_state.get("temp_cleaned"):     # once per session: old left-over temp files
        clean_temp()
        st.session_state["temp_cleaned"] = True
    st.markdown(CSS, unsafe_allow_html=True)
    saved = st.session_state.get("result") if isinstance(st.session_state.get("result"), dict) else None
    if saved and "mode" not in st.session_state:             # the switch shows how the result was made
        st.session_state["mode"] = WITH_JOB if saved.get("with_job") else WITHOUT_JOB
    mode = top_bar(saved)
    if below_top:
        below_top()
    saved = current_result()
    if saved is None:                                         # before a check: the upload card
        inputs = upload_card(mode)
        if inputs is not None:
            check_and_store(inputs, gate)
            if "result" in st.session_state:
                if after_check:
                    after_check(st.session_state["result"])
                st.rerun()                                    # the card hides; the top bar shows the file
        return
    if (mode == WITH_JOB) != bool(saved["with_job"]):
        inputs = again_card(mode, saved)
        if inputs is not None:
            check_and_store(inputs, gate)
            if "result" not in st.session_state:              # the error message stays; the upload card comes back
                return
            if after_check:
                after_check(st.session_state["result"])
            st.rerun()
    render(saved["res"], saved["with_job"], saved["prev"], client=bool((saved.get("inputs") or {}).get("client")),
           swapped=saved.get("swap"))


def check_and_store(inputs, gate=None):
    """Check the CV (and the previous version, if given) and keep the result with the inputs that made it."""
    try:
        with (gate() if gate else contextlib.nullcontext()), \
                st.spinner("Checking the resume (a new job description is read by AI once, then saved)..."):
            res = run_check(inputs["pdf"], inputs["name"], inputs["with_job"], inputs["text"],
                            job_title=inputs.get("job_title"))
            prev = None
            if inputs.get("prev_pdf"):
                prev = run_check(inputs["prev_pdf"], inputs["prev_name"], inputs["with_job"], inputs["text"],
                                 job_title=inputs.get("job_title"))
            st.session_state["result"] = {"res": res, "with_job": inputs["with_job"], "prev": prev,
                                          "swap": inputs.get("swap"), "inputs": inputs}
    except CheckError as e:
        st.session_state.pop("result", None)
        st.error(str(e))
    except Exception as e:                    # anything unexpected: a clear message, not a stack trace
        st.session_state.pop("result", None)
        st.error(f"Something went wrong while checking the resume: {type(e).__name__}: {e}")


if __name__ == "__main__":      # streamlit runs this file as __main__; tests import it without drawing the page
    main()
