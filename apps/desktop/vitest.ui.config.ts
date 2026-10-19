import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "jsdom",
    environmentOptions: { jsdom: { pretendToBeVisual: true } },
    include: ["tests/ui/**/*.test.tsx"],
    restoreMocks: true,
    clearMocks: true,
  },
});
