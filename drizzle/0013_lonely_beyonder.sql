CREATE TABLE `data_source_health` (
	`id` int AUTO_INCREMENT NOT NULL,
	`sourceName` varchar(50) NOT NULL,
	`sourceLabel` varchar(100) NOT NULL,
	`status` enum('healthy','degraded','down','unknown') NOT NULL DEFAULT 'unknown',
	`latencyMs` int,
	`lastSuccessAt` timestamp,
	`lastFailureAt` timestamp,
	`lastError` text,
	`seriesCount` int DEFAULT 0,
	`lastDataDate` varchar(10),
	`checksTotal` int DEFAULT 0,
	`checksSuccess` int DEFAULT 0,
	`uptimePercent` double DEFAULT 100,
	`historyJson` json,
	`createdAt` timestamp NOT NULL DEFAULT (now()),
	`updatedAt` timestamp NOT NULL DEFAULT (now()) ON UPDATE CURRENT_TIMESTAMP,
	CONSTRAINT `data_source_health_id` PRIMARY KEY(`id`)
);
