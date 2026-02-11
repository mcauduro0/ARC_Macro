ALTER TABLE `model_runs` ADD `stateVariablesJson` json;--> statement-breakpoint
ALTER TABLE `model_runs` ADD `legacyDashboardJson` json;--> statement-breakpoint
ALTER TABLE `model_runs` ADD `legacyTimeseriesJson` json;--> statement-breakpoint
ALTER TABLE `model_runs` ADD `legacyRegimeJson` json;--> statement-breakpoint
ALTER TABLE `model_runs` ADD `legacyCyclicalJson` json;