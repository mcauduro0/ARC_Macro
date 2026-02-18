// Test pipeline execution directly
import { executePipeline } from "./server/pipelineOrchestrator.ts";

console.log("Starting pipeline test...");
try {
  const result = await executePipeline("manual", "debug-test");
  console.log("Pipeline result:", JSON.stringify(result, null, 2));
} catch (err) {
  console.error("Pipeline error:", err);
}
process.exit(0);
