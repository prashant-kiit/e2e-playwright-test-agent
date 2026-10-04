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