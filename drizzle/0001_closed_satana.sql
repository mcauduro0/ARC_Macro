CREATE TABLE `model_runs` (
	`id` int AUTO_INCREMENT NOT NULL,
	`runDate` varchar(10) NOT NULL,
	`currentSpot` double NOT NULL,
	`dashboardJson` json NOT NULL,
	`timeseriesJson` json NOT NULL,
	`regimeJson` json NOT NULL,
	`cyclicalJson` json NOT NULL,
	`status` enum('running','completed','failed') NOT NULL DEFAULT 'completed',
	`errorMessage` text,
	`isLatest` boolean NOT NULL DEFAULT false,
	`createdAt` timestamp NOT NULL DEFAULT (now()),
	CONSTRAINT `model_runs_id` PRIMARY KEY(`id`)
);
