# catchme template — Spring Boot (Gradle or Maven). Copy to .prod-parity/app.Dockerfile and adjust.
# Build context is the project root.
FROM eclipse-temurin:21-jdk AS build
WORKDIR /src
COPY . .
RUN if [ -f gradlew ]; then chmod +x gradlew && ./gradlew --no-daemon -x test bootJar; \
    elif [ -f mvnw ]; then chmod +x mvnw && ./mvnw -q -DskipTests package; \
    else echo "no gradlew/mvnw found" && exit 1; fi
RUN mkdir -p /out && find build/libs target -maxdepth 1 -name '*.jar' ! -name '*-plain.jar' 2>/dev/null | head -n 1 | xargs -I{} cp {} /out/app.jar

FROM eclipse-temurin:21-jre
WORKDIR /app
COPY --from=build /out/app.jar app.jar
# Mirror production JVM flags via JAVA_TOOL_OPTIONS in project.json → app.env
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
