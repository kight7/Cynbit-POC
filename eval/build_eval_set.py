"""Generates eval/inquiries.jsonl: 30 synthetic, hand-labelled inbound inquiries.

Labels were written by the author BEFORE running the system. 20 clear, 5 vague, 5 off-scope.
expected_cases = case studies a senior rep would cite (any one in top-3 counts as a hit).
"""
import json
from pathlib import Path

E = []


def add(id, category, text, industry, urgency, expected_cases, primary_need, budget, dm):
    E.append(dict(id=id, category=category, text=text.strip(), industry=industry, urgency=urgency,
                  expected_cases=expected_cases, primary_need=primary_need, budget_present=budget,
                  decision_maker=dm, off_scope=category == "off_scope"))


add("Q01", "clear", """Hi Cynbit team, I'm Ritika, co-founder of CareQ, a telehealth startup in Bangalore (12 people).
Patients describe symptoms in our app and our two on-call doctors can't tell which ones are serious.
We want an AI layer that ranks incoming cases by urgency and pushes red-flag cases to the top.
We have about $35k and want a pilot within 6 weeks.""", "healthcare", "high", ["CS-01"], "ai_ml", True, True)

add("Q02", "clear", """Hello, we are a rural health NGO in Rajasthan working with 2,000 diabetic and hypertensive patients.
We'd like patients to use low-cost BP and glucose devices at home, with readings sent to our doctors and alerts
when something is wrong. Funding is approved from a CSR grant. Target: start rollout in 4-5 months.
Thanks, Anil Sharma, Programme Director""", "healthcare", "medium", ["CS-02"], "iot", True, True)

add("Q03", "clear", """We're a performance-marketing agency managing ad spend for 40 D2C brands across Google, Meta and YouTube.
Our analysts spend 3 days every month building reports and we still move budgets on gut feel.
Looking for an AI tool that recommends budget shifts between channels and automates reporting.
Budget 20-30 lakh INR. - Karan, Head of Growth""", "marketing_adtech", "unknown", ["CS-03"], "ai_ml", True, True)

add("Q04", "clear", """Our comedy festival's ticketing website went down for 40 minutes when the headliner sale opened last month.
We have another big on-sale in January and cannot let it crash again. Need someone to re-architect it for
traffic spikes urgently.
Regards,
Neha Kapoor
Founder, LaughRiot Events""", "entertainment_events", "high", ["CS-04"], "realtime_systems", False, True)

add("Q05", "clear", """Hi, we sell prescription eyeglass frames online (D2C, ~60 employees). Customers hesitate because they can't
see how frames look on their face. We'd like a feature in our mobile app where they can try frames using the
phone camera. Budget around $50k. Want it live before our spring collection in March.""", "fashion", "medium", ["CS-05"], "ar_vr", True, False)

add("Q06", "clear", """We are an organic tea estate in Darjeeling selling in India and Europe. Buyers keep asking where exactly
their tea comes from. We want a QR code on every pack that shows the garden, harvest date and processing steps,
so customers can verify our claims. No fixed deadline yet.
Best, Tenzing, Owner""", "food_supply_chain", "low", ["CS-06"], "blockchain", False, True)

add("Q07", "clear", """I'm the CIO of a 1,500-employee auto-parts manufacturer. Our ERP is 15 years old and the screens are so confusing
that training a new planner takes six weeks and mistakes are common. We don't want to replace the ERP, just
modernise the interface our people use. Budget has been allocated for FY27.""", "enterprise_software", "unknown", ["CS-07"], "ux_modernization", True, True)

add("Q08", "clear", """We run an online test-prep platform for banking exams with 80k students. Everyone gets the same practice sets,
so strong students get bored and weak ones drop out. We want the platform to adapt questions to each student's
weak topics automatically. Can you share an approach? Timeline: 3 months.
Sanjay, CTO, ExamEdge""", "edtech", "medium", ["CS-08"], "ai_ml", False, True)

add("Q09", "clear", """Hi! We're building a screenwriting SaaS where several writers edit the same script at once. Right now edits overwrite
each other and the app lags when more than 5 people are in a document. We need a proper real-time collaboration
engine. We're seed-funded and want to fix this in the next 2 months.""", "saas_collaboration", "high", ["CS-09"], "realtime_systems", True, False)

add("Q10", "clear", """We are a premium fashion label running on Magento. Pages are slow on mobile and we're launching in the UAE, UK and
Singapore next year. We want to move to a headless commerce setup with a fast storefront. Budget USD 150k-200k.
Regards,
Isabelle Moreau
VP Digital, Maison Clair""", "fashion", "low", ["CS-10"], "ecommerce_platform", True, True)

add("Q11", "clear", """We own a chain of 25 consumer-electronics stores across Gujarat. People nearby can't find us on Google and our store
pages don't show up for searches like 'laptop shop near me'. We want more walk-ins from search. Budget is around 8 lakhs
per year. -- Mehul, Marketing Manager""", "ecommerce_retail", "unknown", ["CS-11"], "seo_growth", True, False)

add("Q12", "clear", """Our diagnostics lab network (18 labs, Hyderabad) still runs patient reports from on-premise servers that are failing.
We need to move everything to AWS without any downtime, because doctors access reports 24/7, and we must stay
compliant with health-data rules. Please treat this as urgent.
Dr. Kavya Rao, Director - IT""", "healthcare", "high", ["CS-12"], "cloud_migration", False, True)

add("Q13", "clear", """We are a licensed remittance company in Dubai sending money from the Gulf to India, Nepal and the Philippines.
Our transfer API is slow at peak hours and every new corridor means new compliance rules. We want to rebuild the
payments backend to scale to millions of users. Budget: $250k. Timeline: phase 1 in 4 months.
Omar Khalid, CTO, RemitWave""", "fintech", "medium", ["CS-13"], "payments", True, True)

add("Q14", "clear", """Our hospital's emergency department receives online pre-registration forms with symptoms before patients arrive.
Nurses read each form manually. We'd like AI to flag the critical ones and connect with our patient record
system. Looking to start next quarter.
Regards, Head of Nursing, Sunrise Multispeciality Hospital""", "healthcare", "medium", ["CS-01"], "ai_ml", False, True)

add("Q15", "clear", """We're a D2C skincare brand with a Shopify store. Paid ads are getting too expensive and we want organic traffic
to grow: better rankings, blog content and local pages for the cities we deliver in. Can you send a proposal?
Our budget is $3k per month.""", "ecommerce_retail", "unknown", ["CS-11"], "seo_growth", True, False)

add("Q16", "clear", """We operate a digital lending app with 300k borrowers. Fraud rings are creating fake accounts and we only catch them
after the loan is disbursed. We need real-time fraud detection in the loan approval flow. Budget approved.
Need something in production by February.
Arjun Mehta, Chief Risk Officer, QuickCred""", "fintech", "medium", ["CS-13"], "ai_ml", True, True)

add("Q17", "clear", """We run a corporate training platform used by 120 companies. Employees take the same courses regardless of their
role or skill level. We want to recommend learning paths based on each employee's skill gaps.
Budget around EUR 60k. Timeline is flexible, ideally within 6 months.""", "edtech", "medium", ["CS-08"], "ai_ml", True, False)

add("Q18", "clear", """Our cricket league sells tickets online and every final the booking site freezes when 100k fans log in at once.
We need the booking system rebuilt to handle the rush before next season's final in April.
Regards,
Vikram Singh
COO, Premier T20 League""", "entertainment_events", "medium", ["CS-04"], "realtime_systems", False, True)

add("Q19", "clear", """We're a consumer brand spending heavily across TV, digital ads and influencers, and nobody can tell us which channel
actually drives sales. We'd like a single dashboard with attribution and AI recommendations for where to spend the
next rupee. Budget 50 lakhs. Want this before the festive season in 5 months.
Head of Marketing, Brewly Coffee""", "marketing_adtech", "medium", ["CS-03"], "data_analytics", True, True)

add("Q20", "clear", """We sell ethnic wear online and 30% of our orders come back because of size issues. Could you build something that
helps shoppers see how a kurta or saree would look and fit on them before buying? We're a 40-person company in Jaipur.
Want to launch by the wedding season.""", "fashion", "unknown", ["CS-05"], "ar_vr", False, False)

# --- vague (5)
add("Q21", "vague", """Hello, we are a small clinic and want to go digital. What can you do for us?""",
    "healthcare", "unknown", ["CS-01", "CS-02", "CS-12"], None, False, False)
add("Q22", "vague", """Need an app for my business. Please call me back.""",
    None, "unknown", [], "mobile_app", False, False)
add("Q23", "vague", """Our online store isn't doing well. Can you help us fix it?""",
    "ecommerce_retail", "unknown", ["CS-10", "CS-11", "CS-05"], None, False, False)
add("Q24", "vague", """We want to use AI somehow in our company. Everyone is talking about it. Can we talk?""",
    None, "unknown", ["CS-01", "CS-03", "CS-08"], "ai_ml", False, False)
add("Q25", "vague", """Looking for a technology partner for our school. Let me know your rates.""",
    "edtech", "unknown", ["CS-08"], None, False, False)

# --- off-scope (5)
add("Q26", "off_scope", """Looking for a wedding photographer and videographer for a December wedding in Udaipur. Please share packages.""",
    None, "unknown", [], None, False, False)
add("Q27", "off_scope", """We need 500 printed t-shirts with our logo for the company offsite next month. What's your price per piece?""",
    None, "high", [], None, False, False)
add("Q28", "off_scope", """Can you handle our monthly GST filing and bookkeeping? We are a small trading firm in Delhi.""",
    None, "unknown", [], None, False, False)
add("Q29", "off_scope", """We need a manufacturer for 10,000 PCB circuit boards for our smart plug. Please quote.""",
    None, "unknown", [], None, False, False)
add("Q30", "off_scope", """We want to hire 50 call center agents for our customer support team in Noida. Do you provide manpower?""",
    None, "unknown", [], None, False, False)

assert len(E) == 30
out = Path(__file__).with_name("inquiries.jsonl")
out.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in E) + "\n", encoding="utf-8")
print(f"wrote {len(E)} inquiries -> {out}")
