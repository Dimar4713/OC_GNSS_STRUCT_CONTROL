FROM maven:3.9.11-eclipse-temurin-17 AS build
WORKDIR /build
COPY pom.xml ./
RUN mvn -B -DskipTests dependency:go-offline
COPY src ./src
RUN mvn -B -DskipTests package

FROM eclipse-temurin:17-jre
WORKDIR /app
RUN useradd --system --uid 10001 --create-home orekit
COPY --from=build /build/target/orekit-service-0.1.0-SNAPSHOT.jar /app/orekit-service.jar
ENV OREKIT_PORT=8081
ENV OREKIT_DATA_PATH=/orekit-data
EXPOSE 8081
USER 10001
ENTRYPOINT ["java", "-XX:+ExitOnOutOfMemoryError", "-jar", "/app/orekit-service.jar"]
