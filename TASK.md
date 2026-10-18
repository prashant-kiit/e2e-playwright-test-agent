1. Add Git Ignore Content for Current Tech Stack
2. Use Opencode and OpenAI Model
3. Move to Sandbox
4. How to add Open AI API Key in Sandbox to OpenCode
```bash
set -a; source .env; set +a
opencode service stop
opencode
```
5. Add trigger from Target Application to Opencode e2e Test Agent
6. Target App -> Our Agent -> Pushes code to Some Other Test Repo -> CI Triggers to run Tests in tests/ folder
7. Add User Story MD from React App
8. Run Headless Browser in Opencode playwright agent
9. Handle Timeout
10. Add Logs for Monitoring
11. Splits the Agent in Bounded Scenario
12. Write Tests only for the Changed Part as Per Git History
13. Next Task is to implement the important points from TASK.md
14. Each Test Run should use a new Session of Claude Code in Sandbox
15. Questions asked by Claude Code as Human in the Loop should be reflective on Frontend as well in same form and answers from frontend should go the Claude Code
16. Claude Code should not stop for GitHub user/credential permissions (May be run in auto mode dangerously)
17. Commit and Push should be in Batches Not in Bulk.
18. Understand the flaws in Manual Flow using the Logs.
19. Make Custom Test Target that can be chnaged to have versioned Tests and User Stories.
20. Which folders/files will be inside and outside of the Sandbox.
21. How the permissions will be managed for Claude Code Agent inside the Sandbox.
22. How to handle is something breaks? How to resume from the point of breaking?
23. See if any folder/files are useless. If yes then remove them.
24. Stay minialist.
25. How Multi Tenant Session will be managed?
26. Is Storing the Test Artifacts in File Storage Correct? Or S3 like something be used? 

Next Question:
- Have Very Simple Test Flow for Testing to Save Cost.
- why was scrum-101 was not pused to target repo? Story -> Plan (Specs) -> Code (X) -> Report why? Code Regenerated and Report both should be mark of completion. Based on that Skipping should happen.
- Add Some-Determinism in the Above Mapping using Frontend and SQL DB
- Use Docker Based Object Storage for Artfiacts Storage using Streaming
- Feature to Clean the Artifacts
- How can we have a Every Step Log, HITL Questions and Push Approval? Please discuss.
- Only one version of aritfacts should be maintained. Plywright CI do not belon in this Repo.
- Agent Claude Code must use cheap Model.
- Bootstrapping should be a Separate Step from Frontend.

Agent Repo:
- 

Test Target Repo:
- User Story - Deliverable
- Plan/Specs - Deliverable
- Seed - Deliverable
- Tests Code - Deliverable
- Evidence - Deliverable
- Report - Deliverable
- App.json - For Running Test CI
- Playwright Config - For Running Test CI
- Package - For Running Test CI
- State + Git History for Syncing in case of Breakdown 

Add 3 Tools in this reagrd:
- Bootstrapp - Sync mode with Agent Repo as Source of Truth
- Check Is bootstrapped
- Push Artifacts - Sync mode with Agent Repo as Source of Truth
- Integrate these Tools with Main Agent
- If this means that GitHub MCP is not required then it is Fine
- All these tools should be Reusable
- Run Script (Agent) should run Check is Bootstrapped Tool to. If yes then Agentic workflow should start
- Make Sure that While QA Flow do not break
- Ask me if any questions or loop holes u find.

custom mcp. legacy cleanup. parallel push may lead to git conflicts.
there is only batch mode with Human Review
what is the use playwright-test-report folder and its index.html file
Add Interactivity in batch flow

```bash
set -a; source .env; set +a            # loads GITHUB_PAT (if not already set)
./reset-target.sh --dry-run saucedemo  # preview: what it would wipe (no changes)
./reset-target.sh saucedemo            # do it — asks you to type the repo name to confirm
./bootstrap-target.sh saucedemo        # rebuild the clean infra on master
```