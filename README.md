# Resume Refining & Tailoring System

## Overview
This project is an AI-assisted resume improvement system with two focused flows: **Refinery** for role-based gap analysis and **Tailor** for job-specific resume tailoring. It identifies capability gaps, proposes grounded improvements, and supports review before applying changes. Export produces validation-safe DOCX outputs built from structured resume data.

<img width="1920" height="685" alt="Refinery" src="https://github.com/user-attachments/assets/8e136f9d-ba5a-4134-990a-1544db51416e" />
<img width="1920" height="945" alt="Tailor" src="https://github.com/user-attachments/assets/4ff07ce4-8acf-4d5d-95d0-2e4af6ed655e" />

## Key Features
- Refinery: role-based gap analysis and actionable recommendations
- Tailor: job-specific resume optimization
- Diff View + Selective Apply
- Structured DOCX export with validation safeguards
- No hallucinated experience - grounded transformations only

## Why this exists
Most resume tools rewrite content blindly.

This system:
- identifies real capability gaps
- separates signal from noise
- avoids misleading or fabricated experience
- focuses on credibility, not just wording

## Demo Flow
### Refinery
1. Upload resume
2. Run analysis
3. Review gaps
4. Apply improvements
5. Export

### Tailor
1. Upload resume
2. Paste job description
3. Tailor resume
4. Review changes
5. Export DOCX

## Tech Stack
- FastAPI (Python)
- React + TypeScript
- Structured transformation pipeline
- python-docx for export

## Local Setup
### Backend
1. `cd backend`
2. Install dependencies: `pip install -r requirements.txt`
3. Run server: `uvicorn app.main:app --reload`

### Frontend
1. `cd frontend`
2. Install dependencies: `npm install`
3. Start dev server: `npm run dev`

## Notes
- Designed to prevent unsafe or misleading resume outputs
- Emphasizes structured reasoning over blind rewriting
