004. Cloud platform: AWS, via AWS re/Start

Date: 2026-09-06 (backfilled — decision effectively made when AWS re/Start was chosen as the enrollment path) Status: Accepted

Context

The lab's Phase 6 (Terraform/IaC) and general employability plan both require a cloud platform. AWS and Azure were both live candidates, discussed twice, with reasoning pulling in different directions each time:

AWS: broader job posting volume, more remote-first listings, largest free study community, AWS SAA is the most-named cloud credential in target job descriptions.
Azure: stronger fit for the federal/enterprise-adjacent target market given this lab's Maryland location near the Fort Meade corridor, gentler entry point (AZ-900), certifications that renew free annually rather than expiring every 3 years, and better alignment with the identity-and-directory-services stack (Entra ID, Active Directory) that shows up in federal contractor job postings such as the Leidos Windows Server Administrator role reviewed against this résumé.

No clear winner emerged from reasoning alone — the two paths favored different parts of the same overall plan. The question was reopened a second time before a new factor resolved it: a free, self-paced, AWS re/Start structured bootcamp track, including AWS Cloud Practitioner certification and job placement support, and an explicit target of the "Cloud Support Associate" and "Junior Systems Administrator" titles already used elsewhere in this plan.

Options considered

1. Azure first, via AZ-900 self-study. Better geographic and federal-market fit on paper. Requires paying for the exam (~$99) and studying alone, with no structured curriculum or placement support.

2. AWS first, via AWS re/Start. Free, self-paced, structured, includes a real credential (AWS Cloud Practitioner) and job placement assistance. Directly names the same target job titles already established in this plan. Moves the platform decision away from the theoretically better regional fit and toward the practically stronger support structure.

3. Both simultaneously. Rejected outright as a repeat of the acquisition-over-progress pattern already flagged multiple times in this lab's history (parallel Linux courses, unused snap packages, recurring hardware research) — splitting effort across two clouds before finishing either serves neither.

Decision

Option 2 — AWS, via AWS re/Start.

Deciding factor: free structured training with job placement support outweighs a theoretically better platform-to-region fit that would otherwise require paid, unstructured self-study with no support network. Azure is not rejected — it is explicitly deferred.

The cross-platform transfer argument, established in the original AWS vs. Azure discussion, still holds and is the basis for treating this as resolvable in sequence rather than requiring a permanent choice: VPC and VNet, IAM and Entra ID, S3 and Blob Storage are conceptually equivalent once one platform is understood, so a second cloud credential taken later is expected to take a fraction of the time the first one did.

Consequences

Positive

Removes cost as a barrier to starting cloud study at all.
Comes with structured curriculum and job placement support that self-study alone does not provide.
Directly targets the exact job titles ("Cloud Support Associate," "Junior Systems Administrator") already established as this lab's employment goal, rather than a generic fundamentals credential.
If AWS re/Start leads to employment, Azure (or any other platform) becomes a post-employment decision made with income, production experience, and likely employer-funded training behind it — a materially stronger position than self-studying while job-hunting.

Negative

The federal/enterprise-market and identity-stack advantages previously identified for Azure are deferred, not captured now. If the actual first job lands in a Microsoft-stack-heavy environment (as the reviewed Leidos posting suggests is common in this region), the credential in hand will not match the employer's primary stack on day one.
AWS re/Start's schedule format and whether it is genuinely self-paced with no fixed deadlines was not independently verified beyond what was stated when the program was discussed — worth confirming directly with admissions before treating the "runs alongside everything else" assumption as settled.

Neutral

Phase 6 (Terraform) in this lab's plan will use AWS as its target provider as a consequence of this decision, rather than Azure.
Follow-up
 Confirm AWS re/Start's actual schedule structure and whether cohort deadlines exist despite "self-paced" framing
 Revisit Azure (AZ-900 or AZ-104) as a second-cloud credential once employed, or sooner if a specific job application demonstrates a hard Azure requirement this decision didn't anticipate
Project content
Linux
Created by you
Add PDFs, documents, or other text to reference in this project.
Content
Resume.docx

DOCX
