# Login with valid credentials

A local test ticket in the qualfy contract. GitHub issues and Jira tickets (for example written by
a Rovo agent) use the same fenced YAML block.

```yaml
key: EXAMPLE-1
cases:
  - id: TC-1
    title: User logs in with valid credentials
    priority: high
    preconditions: [An active user exists]
    steps:
      - Open the login page
      - Fill in username and password
      - action: Submit the form
        expected: [The dashboard is shown]
    expected: [The user name is visible in the header]
  - id: TC-2
    title: Error on wrong password
    steps:
      - Open the login page
      - Submit a valid username with a wrong password
    expected: [An "Invalid credentials" message is shown]
  - id: TC-3
    title: Visual check of the login page branding
    automatable: false
    steps: [Review the page against the brand guidelines]
```
