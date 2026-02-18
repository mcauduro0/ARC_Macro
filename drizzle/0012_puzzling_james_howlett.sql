CREATE TABLE `pipeline_runs` (
	`id` int AUTO_INCREMENT NOT NULL,
	`triggerType` enum('manual','scheduled','startup') NOT NULL,
	`triggeredBy` varchar(100),
	`status` enum('running','completed','failed','partial') NOT NULL DEFAULT 'running',
	`currentStep` varchar(50),
	`totalSteps` int NOT NULL DEFAULT 6,
	`completedSteps` int NOT NULL DEFAULT 0,
	`stepsJson` json,
	`modelRunId` int,
	`alertsGenerated` int DEFAULT 0,
	`summaryJson` json,
	`errorMessage` text,
	`startedAt` timestamp NOT NULL DEFAULT (now()),
	`completedAt` timestamp,
	`durationMs` int,
	`createdAt` timestamp NOT NULL DEFAULT (now()),
	CONSTRAINT `pipeline_runs_id` PRIMARY KEY(`id`)
);
