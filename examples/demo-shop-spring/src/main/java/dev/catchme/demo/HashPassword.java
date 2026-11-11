package dev.catchme.demo;

import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;

/**
 * Prints a BCrypt hash with the same encoder the app uses (for catchme test accounts):
 * java -cp app.jar -Dloader.main=dev.catchme.demo.HashPassword \
 *   org.springframework.boot.loader.launch.PropertiesLauncher catchme-test
 */
public class HashPassword {
    public static void main(String[] args) {
        System.out.println(new BCryptPasswordEncoder().encode(args.length > 0 ? args[0] : "catchme-test"));
    }
}
