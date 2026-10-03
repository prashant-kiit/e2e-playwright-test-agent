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