package com.example.dod;

import com.example.dod.config.PrototypeProperties;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.EnableConfigurationProperties;

@SpringBootApplication
@EnableConfigurationProperties(PrototypeProperties.class)
public class DodApplication {

    public static void main(String[] args) {
        SpringApplication.run(DodApplication.class, args);
    }

}
