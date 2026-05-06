package com.aihumanloop.ingestion;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableScheduling;

@SpringBootApplication
@EnableScheduling
public class TicketIngestionApplication {
    public static void main(String[] args) {
        SpringApplication.run(TicketIngestionApplication.class, args);
    }
}
