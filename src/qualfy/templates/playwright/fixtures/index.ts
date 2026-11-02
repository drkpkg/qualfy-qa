import { test as base } from "@playwright/test";

type Credentials = { username: string; password: string };

export const test = base.extend<{ credentials: Credentials }>({
  credentials: async ({}, use) => {
    await use({
      username: process.env.TEST_USER ?? "",
      password: process.env.TEST_PASSWORD ?? process.env.QUALFY_ANSWER_TEST_PASSWORD ?? "",
    });
  },
});

export { expect } from "@playwright/test";
